"""
Gemini Browser Manager - 管理Gemini浏览器会话（无头模式）

支持功能：
- 多账户管理（使用数字编号区分不同账户）
- 使用保存的浏览器状态自动登录
- 无头模式运行

用法：
    python gemini_browser.py run [账户编号]   # 运行浏览器会话
    python gemini_browser.py list             # 列出所有已保存的账户

示例：
    python gemini_browser.py run 0    # 使用账户0运行
    python gemini_browser.py list     # 列出所有账户
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from .browser import DEFAULT_PERMISSIONS, DEFAULT_VIEWPORT, get_launch_args


class GeminiBrowser:
    """Gemini浏览器管理器（无头模式）"""

    def __init__(
        self,
        account_id: int = 0,
        headless: bool = True,
        proxy: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
    ):
        self.account_id = account_id
        self.headless = True  # 始终使用无头模式
        self.proxy = proxy
        self.base_dir = Path(__file__).parent.parent / "data"

        # 数据目录：优先使用 /app/data，否则使用代码目录（本地开发）
        data_dir = Path("/app/data") if Path("/app/data").exists() else self.base_dir

        # 允许外部指定 user_data_dir
        if user_data_dir:
            self.user_data_dir = (
                Path(user_data_dir) if isinstance(user_data_dir, str) else user_data_dir
            )
        else:
            self.user_data_dir = data_dir / "browser_data" / str(account_id)

        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def launch(self, timeout: int = 60000) -> Page:
        """
        启动浏览器并访问Gemini

        Args:
            timeout: 页面加载超时时间（毫秒）

        Returns:
            Page对象，可用于后续操作
        """
        # 检查目录是否存在，如果不存在则创建
        if not self.user_data_dir.exists():
            print(f"⚠️  创建浏览器数据目录: {self.user_data_dir}")
            self.user_data_dir.mkdir(parents=True, exist_ok=True)

        # # 检查是否有登录状态（cookies）todo：不准确，现在不使用start.sh 登陆
        # cookies_file = self.user_data_dir / "cookies.json"
        # has_cookies = cookies_file.exists()

        # if not has_cookies:
        #     print(f"⚠️  警告: 账户 {self.account_id} 未登录 Google")
        #     print("   首次使用需要手动登录，浏览器会自动保存登录状态")
        #     print(f"   或运行: python gemini_browser.py login {self.account_id}")

        print("=" * 60)
        print(f"启动Gemini浏览器 - 账户 {self.account_id} (无头模式)")
        print("=" * 60)
        print(f"数据目录: {self.user_data_dir}")

        # 创建playwright实例并保持
        self.playwright = await async_playwright().start()

        # 使用统一的启动参数配置
        launch_args = get_launch_args(proxy=self.proxy)

        if self.proxy:
            print(f"使用代理: {self.proxy}")

        # 使用保存的持久化上下文
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=True,
            viewport=DEFAULT_VIEWPORT,
            args=launch_args,
            permissions=DEFAULT_PERMISSIONS,
        )

        self.page = (
            self.context.pages[0]
            if self.context.pages
            else await self.context.new_page()
        )

        print("\n正在访问 Gemini...")
        await self.page.goto(
            "https://gemini.google.com/app",
            wait_until="load",
            timeout=timeout,
        )

        # 检查登录状态
        title = await self.page.title()
        url = self.page.url
        print("\n✓ 页面已加载")
        print(f"  标题: {title}")
        print(f"  URL: {url}")

        return self.page

    async def close(self):
        """关闭浏览器"""
        if self.context:
            await self.context.close()
            print("\n✓ 浏览器已关闭")

        if self.playwright:
            await self.playwright.stop()
