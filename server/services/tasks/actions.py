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
    "model_menu": '[data-test-id="bard-mode-menu-button"]',
    "model_fast": [
        '[data-test-id="bard-mode-option-fast"]',
        '[data-test-id="bard-mode-option-快速"]',
        '[data-test-id="bard-mode-option-Flash"]',
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

async def start_new_chat(page: Page) -> bool:
    """开启新对话"""
    try:
        if "/app" in page.url:
            await page.keyboard.press("Control+Shift+O")
        else:
            await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            
        await page.wait_for_selector(_SELECTORS["input_box"], timeout=10000)
        return True
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

async def set_model(page: Page, model: str = "Fast"):
    """切换模型"""
    target = _SELECTORS["model_fast"] if model == "Fast" else _SELECTORS["model_pro"]
    try:
        menu_btn = await page.wait_for_selector(_SELECTORS["model_menu"], timeout=5000)
        text = await menu_btn.inner_text()
        
        is_already = ("Fast" in text or "快速" in text or "Flash" in text) if model == "Fast" else ("Pro" in text)
        if is_already: return True

        await menu_btn.click()
        for sel in target:
            try:
                opt = await page.wait_for_selector(sel, timeout=2000, state="visible")
                if opt:
                    await opt.click()
                    return True
            except: continue
        return False
    except:
        return False

async def ensure_image_gen_active(page: Page):
    """确保图片生成功能开启"""
    if await page.query_selector(_SELECTORS["image_gen_deselect"]):
        return True
    
    for sel in _SELECTORS["tools_btn"]:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000)
            await btn.click()
            break
        except: continue
        
    for sel in _SELECTORS["image_gen_opt"]:
        try:
            opt = await page.wait_for_selector(sel, timeout=3000)
            await opt.evaluate("el => el.click()")
            return True
        except: continue
    return False

async def input_prompt(page: Page, prompt: str):
    """输入提示词"""
    box = await page.wait_for_selector(_SELECTORS["input_box"], timeout=5000)
    await box.fill(prompt)
    return True

async def upload_image(page: Page, image_path: str):
    """粘贴图片上传"""
    img_file = Path(image_path)
    if not img_file.exists(): return False
    
    with open(img_file, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    return await page.evaluate("""
        async ([b64, selector]) => {
            const res = await fetch(`data:image/webp;base64,${b64}`);
            const blob = await res.blob();
            const file = new File([blob], "input.webp", { type: "image/webp" });
            const dt = new DataTransfer();
            dt.items.add(file);
            const target = document.querySelector(selector);
            target.focus();
            target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
            return true;
        }
    """, [img_b64, _SELECTORS["input_box"]])

async def click_submit(page: Page):
    """点击提交"""
    for sel in _SELECTORS["submit_btns"]:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000, state="visible")
            await btn.click()
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
        for sel in _SELECTORS["download_btns"]:
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

async def handle_consent_popups(page: Page):
    """处理各种同意弹窗"""
    for sel in _SELECTORS["agree_btns"]:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
        except: pass

async def reinitialize_page(page: Page, model: str = "Fast") -> bool:
    """初始化/重置页面环境"""
    try:
        await page.goto("https://gemini.google.com/app", wait_until="load", timeout=60000)
        return await prepare_environment(page, model)
    except:
        return False
