"""
Gemini 原子动作 - 封装了所有物理选择器和原始交互
"""

import asyncio
import base64
import hashlib
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from PIL import Image
from playwright.async_api import Page

from .remove_watermark.main import WatermarkRemover

# =========================================================================
# 物理层定位符 (内部隐藏)
# =========================================================================

_SELECTORS = {
    "input_box": 'div[contenteditable="true"]',
    "submit_btns": [
        'button[aria-label*="发送"]',
        'button[aria-label*="Send"]',
        'button[aria-label*="submit"]',
        'button[data-test-id="send-button"]',
    ],
    "model_menu": [
        '[data-test-id="bard-mode-menu-button"]',
        'button[aria-label*="Model"]',
        'button[aria-label*="模型"]',
    ],
    "model_fast": [
        '[data-test-id="bard-mode-option-fast"]',
        '[data-test-id="bard-mode-option-快速"]',
        '[data-test-id="bard-mode-option-Flash"]',
    ],
    "model_thinking": [
        '[data-test-id="bard-mode-option-thinking"]',
        '[data-test-id="bard-mode-option-思考"]',
        '[data-test-id="bard-mode-option-Thinking"]',
    ],
    "model_pro": [
        '[data-test-id="bard-mode-option-pro"]',
        '[data-test-id="bard-mode-option-Pro"]',
    ],
    "tools_btn": [
        "button.toolbox-drawer-button",
        'button[aria-label="工具"]',
        'button[aria-label="Tools"]',
    ],
    "image_gen_opt": ["text=Create images", "text=生成图片"],
    "image_gen_deselect": ".toolbox-drawer-item-deselect-button",
    "response_container": ["model-response", "response-container"],
    "download_btns": [
        'button[aria-label*="Download"]',
        'button[aria-label*="下载"]',
        'button[aria-label*="保存"]',
    ],
    "agree_btns": [
        'button:has-text("Agree")',
        'button:has-text("同意")',
        'button:has-text("OK")',
        '[role="dialog"] button[data-mdc-dialog-action="accept"]',
    ],
}

_AVATAR_PATTERN = "/a/ACg8oc"

# =========================================================================
# 原子动作 (Verbs)
# =========================================================================

async def start_new_chat(page: Page, selector: str = _SELECTORS["input_box"]) -> bool:
    """开启新对话"""
    try:
        # 1. 优先尝试快捷键
        if "/app" in page.url:
            await page.keyboard.press("Control+Shift+O")
            await asyncio.sleep(0.5)
        
        # 2. 如果 URL 不对，强行跳转
        if "/app" not in page.url:
            await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            
        # 3. 检查输入框是否出现 (判定为成功)
        try:
            await page.wait_for_selector(selector, timeout=5000)
            return True
        except:
            # 4. 兜底：尝试点击页面上的 New Chat 按钮 (针对快捷键失效的情况)
            new_btn = await page.query_selector('a[href="/app"], .new-chat-button')
            if new_btn: 
                await new_btn.click()
                await page.wait_for_selector(selector, timeout=5000)
                return True
        return False
    except:
        return False

async def prepare_environment(page: Page, model: str = "Fast") -> bool:
    """准备页面环境：切换模型并确保功能开启"""
    await handle_consent_popups(page)
    await start_new_chat(page)
    
    # 切换模型
    await set_model(page, model)
    
    # 激活图片生成 (如果需要)
    await ensure_image_gen_active(page)
    return True

async def select_menu_item(page: Page, item_selectors: List[str], menu_selectors: List[str] = _SELECTORS["model_menu"]) -> bool:
    """原子动作：点击下拉菜单并从中选择一项 (优化版本：利用 CSS 组选择器)"""
    try:
        # 1. 一次性等待任何一个可能的菜单按钮
        all_menus = ", ".join(menu_selectors)
        menu_btn = await page.wait_for_selector(all_menus, timeout=5000, state="visible")
        await menu_btn.click()
        
        # 2. 一次性等待任何一个可能的待选项
        all_items = ", ".join(item_selectors)
        opt = await page.wait_for_selector(all_items, timeout=3000, state="visible")
        if opt:
            try:
                await opt.click(timeout=2000)
            except:
                await opt.evaluate("el => el.click()")
            return True
    except:
        pass
    return False

async def ensure_image_gen_active(page: Page) -> bool:
    """业务动作：确保图片生成功能开启"""
    if await page.query_selector(_SELECTORS["image_gen_deselect"]):
        return True
    
    # 传入列表，原子函数内部会自动遍历重试
    return await select_menu_item(page, _SELECTORS["image_gen_opt"], menu_selectors=_SELECTORS["tools_btn"])

async def set_model(page: Page, model: str = "Fast"):
    """业务动作：切换模型 (内置预检优化，支持 Fast/Pro/Thinking)"""
    model_key = model.lower()
    mapping = {
        "fast": ("model_fast", ["Fast", "快速", "Flash"]),
        "flash": ("model_fast", ["Fast", "快速", "Flash"]),
        "pro": ("model_pro", ["Pro"]),
        "thinking": ("model_thinking", ["Thinking", "思考"]),
        "thought": ("model_thinking", ["Thinking", "思考"]),
    }
    
    config = mapping.get(model_key)
    if not config:
        return False # 不支持的模型
        
    selector_key, keywords = config
    target_selectors = _SELECTORS[selector_key]
    
    # 状态预检：如果当前模型已对，则不点击
    try:
        # 利用 CSS 组选择器一次性获取当前活动的菜单按钮文本
        all_menus = ", ".join(_SELECTORS["model_menu"])
        menu_btn = await page.wait_for_selector(all_menus, timeout=3000)
        current_text = await menu_btn.inner_text()
        
        if any(kw in current_text for kw in keywords):
            return True
    except: pass

    return await select_menu_item(page, item_selectors=target_selectors, menu_selectors=_SELECTORS["model_menu"])

async def input_prompt(page: Page, prompt: str, selector: str = _SELECTORS["input_box"]):
    """输入提示词"""
    box = await page.wait_for_selector(selector, timeout=5000)
    await box.fill(prompt)
    return True

async def upload_image(page: Page, image_path: str, selector: str = _SELECTORS["input_box"]):
    """粘贴图片上传"""
    img_file = Path(image_path)
    if not img_file.exists(): return False
    
    with open(img_file, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    return await page.evaluate("""
        async ([b64, target_selector]) => {
            const res = await fetch(`data:image/webp;base64,${b64}`);
            const blob = await res.blob();
            const file = new File([blob], "input.webp", { type: "image/webp" });
            const dt = new DataTransfer();
            dt.items.add(file);
            const target = document.querySelector(target_selector);
            target.focus();
            target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
            return true;
        }
    """, [img_b64, selector])

async def click_submit(page: Page, selectors: List[str] = _SELECTORS["submit_btns"]):
    """点击提交 (采用物理点击+JS点击双重保障)"""
    for sel in selectors:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                try:
                    await btn.click(timeout=2000)
                except:
                    # 针对按钮被遮挡或处于特殊状态，尝试 JS 强制点击
                    await btn.evaluate("el => el.click()")
                return True
        except: continue
    return False

async def wait_for_results(page: Page, timeout_s: int = 60):
    """等待结果生成完成"""
    try:
        await page.wait_for_function(f"""
            () => {{
                const containers = document.querySelectorAll('model-response, response-container');
                if (containers.length === 0) return false;
                const last = containers[containers.length - 1];
                const imgs = Array.from(last.querySelectorAll('img'));
                return imgs.some(i => i.src.includes('googleusercontent') && !i.src.includes('{_AVATAR_PATTERN}'));
            }}
        """, timeout=timeout_s * 1000)
        return True
    except:
        return False

async def get_generated_urls(page: Page) -> List[str]:
    """获取生成的图片 URL 列表"""
    return await page.evaluate(f"""
        () => {{
            const containers = document.querySelectorAll('model-response, response-container');
            if (containers.length === 0) return [];
            const last = containers[containers.length - 1];
            return Array.from(last.querySelectorAll('img'))
                .map(i => i.src)
                .filter(src => src.includes('googleusercontent') && !src.includes('{_AVATAR_PATTERN}'));
        }}
    """)

async def download_image(page: Page, img_url: str, save_path: str, remove_wm: bool = True):
    """下载图片并处理"""
    # 找到对应的预览图元素
    img_element = await page.query_selector(f'img[src="{img_url}"]')
    
    # 1. 尝试 Hover 下载高清
    if img_element:
        await img_element.hover()
        download_btn = None
        current_selectors = _SELECTORS["download_btns"]
        for sel in current_selectors:
            try:
                download_btn = await page.wait_for_selector(sel, timeout=2000, state="visible")
                if download_btn: break
            except: continue
            
        if download_btn:
            try:
                async with page.expect_download(timeout=10000) as download_info:
                    await download_btn.click()
                download = await download_info.value
                path = await download.path()
                if path:
                    return await _process_and_save(path, save_path, remove_wm)
            except: pass

    # 2. 备选方案：直接请求预览图
    response = await page.request.get(img_url)
    if response.ok:
        return await _process_and_save(BytesIO(await response.body()), save_path, remove_wm)
    
    return False, None

async def _process_and_save(src: Any, dest: str, remove_wm: bool):
    """图片后处理内部函数"""
    try:
        img = Image.open(src)
        if remove_wm:
            img = WatermarkRemover.remove_watermark(img)
        
        final_p = Path(dest).with_suffix(".webp")
        final_p.parent.mkdir(parents=True, exist_ok=True)
        img.save(final_p, "WEBP", lossless=True)
        
        with open(final_p, "rb") as f:
            h = base64.urlsafe_b64encode(hashlib.sha256(f.read()).digest()).decode().rstrip("=")
        return True, h
    except:
        return False, None

async def handle_consent_popups(page: Page, selectors: List[str] = _SELECTORS["agree_btns"]) -> bool:
    """处理各种同意弹窗"""
    found = False
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                found = True
        except: pass
    return found

async def reinitialize_page(page: Page, model: str = "Fast") -> bool:
    """初始化/重置页面环境"""
    try:
        await page.goto("https://gemini.google.com/app", wait_until="load", timeout=60000)
        return await prepare_environment(page, model)
    except:
        return False
