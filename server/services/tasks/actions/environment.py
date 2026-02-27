import asyncio
import os
from typing import List, Optional
from playwright.async_api import Page
from server.utils.logger import tab_log
from .selectors import _SELECTORS
from .base import click, input_prompt

async def login_go(page: Page) -> bool:
    """[Login] 点击登录按钮"""
    return await click(page, _SELECTORS["sign_in_btns"])

async def login_account(page: Page, account: Optional[str] = None) -> bool:
    """[Login] 输入账号并点击下一步"""
    if not account:
        account = getattr(page, "_account_name", "")
    
    # 1. 针对 Google 登录页面的账号输入框
    selector_input = "#identifierId"
    if await input_prompt(page, account, selector=selector_input):
        # 2. 点击下一步 (click 内部自带 wait_for_selector)
        selector_next = ["#identifierNext", 'button:has-text("Next")', 'button:has-text("下一步")']
        return await click(page, selector_next)
    return False

async def login_pass(page: Page, password: Optional[str] = None) -> bool:
    """[Login] 输入密码并提交"""
    if not password:
        password = os.getenv("DEFAULT_ACCOUNT_PASSWORD", "")
    
    # 1. 输入密码
    if await input_prompt(page, password, selector="#password"):
        # 2. 点击确认/下一步
        selector_next = ["#passwordNext", 'button:has-text("Next")', 'button:has-text("下一步")']
        return await click(page, selector_next)
    return False

async def login(page: Page, account: Optional[str] = None, password: Optional[str] = None) -> bool:
    """[Login] 一键三连：点击登录 -> 输入账号 -> 输入密码"""
    tab_log(page, "Starting unified login process...")
    
    # 1. 尝试点击首页的登录按钮
    if await login_go(page):
        tab_log(page, "Waiting for login page to settle...")
        await asyncio.sleep(2.5) # 给页面跳转和脚本加载留出“人类感”时间
    
    # 2. 账号阶段
    tab_log(page, "Entering account...")
    if not await login_account(page, account):
        tab_log(page, "Login failed at account stage", "error")
        return False
    
    # 点击“下一步”后，Google 会进行各种反爬校验和转场
    await asyncio.sleep(2.0)
        
    # 3. 密码阶段
    tab_log(page, "Entering password...")
    if not await login_pass(page, password):
        tab_log(page, "Login failed at password stage", "error")
        return False
        
    tab_log(page, "Login process completed successfully")
    return True

# 注意：为了避免循环引用，business 中的函数由 __init__ 统一分发，或者 environment 只依赖 selectors 和 base
# 这里暂时只放环境相关的原子组合

async def handle_consent_popups(page: Page, selectors: List[str] = _SELECTORS["agree_btns"]) -> bool:
    """处理各种同意弹窗"""
    if isinstance(selectors, str): selectors = [selectors]
    combined_sel = ", ".join(selectors)
    try:
        btn = await page.query_selector(combined_sel)
        if btn and await btn.is_visible():
            await btn.click()
            return True
    except: pass
    return False

async def prepare_environment(page: Page, model: str = "Fast") -> bool:
    """准备页面环境：切换模型并确保功能开启"""
    from .business import start_new_chat, set_model, ensure_image_gen_active # 局部导入避免循环引用
    
    await handle_consent_popups(page)
    
    # 1. 快速检查是否出现了登录按钮
    try:
        combined_signin = ", ".join(_SELECTORS["sign_in_btns"])
        if await page.query_selector(combined_signin):
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
    except Exception as e:
        tab_log(page, f"Page reinitialization failed: {e}", "error")
        return False
