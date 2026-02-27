import asyncio
import base64
from pathlib import Path
from typing import List
from playwright.async_api import Page
from server.utils.logger import tab_log
from .selectors import _SELECTORS

async def click(page: Page, selectors: List[str]):
    """通用点击动作 (支持多选择器回退，不含业务逻辑检查)"""
    # 鲁棒性：支持单字符串
    if isinstance(selectors, str): selectors = [selectors]
    
    for sel in selectors:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                try:
                    await btn.click(timeout=2000)
                except:
                    # 原生物理强制点击，穿透遮罩层
                    await btn.click(timeout=2000, force=True)
                return True
        except: continue
    return False

async def input_prompt(page: Page, prompt: str, selector: str = _SELECTORS["input_box"]):
    """输入提示词"""
    box = await page.wait_for_selector(selector, timeout=5000)
    await box.fill(prompt)
    return True

async def select_menu_item(page: Page, item_selectors: List[str], menu_selectors: List[str] = _SELECTORS["model_menu"]) -> bool:
    """原子动作：点击下拉菜单并从中选择一项 (优化版本：利用 CSS 组选择器)"""
    # 鲁棒性：支持单字符串
    if isinstance(item_selectors, str): item_selectors = [item_selectors]
    if isinstance(menu_selectors, str): menu_selectors = [menu_selectors]
    
    try:
        # 1. 一次性等待任何一个可能的菜单按钮
        all_menus = ", ".join(menu_selectors)
        menu_btn = await page.wait_for_selector(all_menus, timeout=15000, state="visible")
        try:
            await menu_btn.click(timeout=2000)
        except:
            await menu_btn.click(timeout=2000, force=True)
        
        # 2. 一次性等待任何一个可能的待选项
        all_items = ", ".join(item_selectors)
        opt = await page.wait_for_selector(all_items, timeout=15000, state="visible")
        if opt:
            try:
                await opt.click(timeout=2000)
            except:
                await opt.click(timeout=2000, force=True)
            return True
    except Exception as e:
        tab_log(page, f"select_menu_item error: {e}", "error")
    return False

async def upload_image(page: Page, image_path: str, selector: str = _SELECTORS["input_box"]):
    """粘贴图片上传 (非阻塞版：仅触发粘贴)"""
    img_file = Path(image_path)
    if not img_file.exists(): return False
    
    with open(img_file, "rb") as f:
        img_data = f.read()
        img_b64 = base64.b64encode(img_data).decode()
    
    # 使用原始文件名，避免 Gemini 的"你已经上传过"重复检测
    filename = img_file.name
    
    return await page.evaluate("""
        async ([b64, target_selector, fname]) => {
            const res = await fetch(`data:image/webp;base64,${b64}`);
            const blob = await res.blob();
            const file = new File([blob], fname, { type: "image/webp" });
            const dt = new DataTransfer();
            dt.items.add(file);
            const target = document.querySelector(target_selector);
            if (!target) return false;
            target.focus();
            target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
            return true;
        }
    """, [img_b64, selector, filename])

async def get_uploaded_image_count(page: Page) -> int:
    """原子动作：获取当前输入框中已物理存在的图片预览数量"""
    try:
        # 使用 blob 图片作为可靠的计数依据（确保图片实际已加载）
        count = await page.evaluate("""
            () => document.querySelectorAll('img[src*="blob:"]').length
        """)
        return int(count or 0)
    except:
        return 0
