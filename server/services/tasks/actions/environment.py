from typing import List
from playwright.async_api import Page
from server.utils.logger import tab_log
from .selectors import _SELECTORS

# 注意：为了避免循环引用，business 中的函数由 __init__ 统一分发，或者 environment 只依赖 selectors 和 base
# 这里暂时只放环境相关的原子组合

async def handle_consent_popups(page: Page, selectors: List[str] = _SELECTORS["agree_btns"]) -> bool:
    """处理各种同意弹窗"""
    if isinstance(selectors, str): selectors = [selectors]
    found = False
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                found = True
        except: pass
    return found

async def prepare_environment(page: Page, model: str = "Fast") -> bool:
    """准备页面环境：切换模型并确保功能开启"""
    from .business import start_new_chat, set_model, ensure_image_gen_active # 局部导入避免循环引用
    
    await handle_consent_popups(page)
    
    # 1. 快速检查是否出现了登录按钮
    for sel in _SELECTORS["sign_in_btns"]:
        try:
            if await page.query_selector(sel):
                tab_log(page, "Login required (Sign-in button detected)", "warning")
                return False
        except: pass

    # 2. 检查是否有核心输入框
    if not await start_new_chat(page):
        tab_log(page, "Environment check failed: Input box not found", "error")
        return False
    
    # 3. 必须能成功切换模型
    if not await set_model(page, model):
        tab_log(page, f"Environment check failed: Failed to set model {model}", "error")
        return False
    
    # 4. 必须能成功开启图片生成功能 
    if not await ensure_image_gen_active(page):
        tab_log(page, "Environment check failed: Cannot activate image generation", "error")
        return False
        
    return True

async def reinitialize_page(page: Page, model: str = "Fast") -> bool:
    """初始化/重置页面环境"""
    try:
        await page.goto("https://gemini.google.com/app", wait_until="load", timeout=60000)
        return await prepare_environment(page, model)
    except:
        return False
