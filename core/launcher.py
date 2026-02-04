"""
Gemini 浏览器启动器 - 负责 Playwright 实例的管理
"""

import asyncio
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page, async_playwright

from .gemini import DEFAULT_PERMISSIONS, DEFAULT_VIEWPORT, get_launch_args


class GeminiLauncher:
    """Gemini 浏览器启动器"""

    def __init__(
        self,
        account_id: int = 0,
        proxy: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
    ):
        self.account_id = account_id
        self.proxy = proxy

        # 数据目录
        self.base_dir = Path(__file__).parent.parent / "data"
        data_dir = Path("/app/data") if Path("/app/data").exists() else self.base_dir

        if user_data_dir:
            self.user_data_dir = (
                Path(user_data_dir) if isinstance(user_data_dir, str) else user_data_dir
            )
        else:
            self.user_data_dir = data_dir / "browser_data" / str(account_id)

        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def _parse_proxy(self, proxy_url: str) -> Optional[Dict[str, str]]:
        """解析代理 URL"""
        if not proxy_url:
            return None
        try:
            parsed = urlparse(proxy_url)
            server = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server += f":{parsed.port}"
            proxy_config = {"server": server}
            if parsed.username:
                proxy_config["username"] = parsed.username
            if parsed.password:
                proxy_config["password"] = parsed.password
            return proxy_config
        except Exception as e:
            print(f"代理 URL 解析失败: {e}")
            return None

    async def launch(self, timeout: int = 60000, headless: bool = True) -> Page:
        """启动浏览器并访问 Gemini"""
        if not self.user_data_dir.exists():
            self.user_data_dir.mkdir(parents=True, exist_ok=True)

        print(f"启动 Gemini 浏览器 - 账户 {self.account_id}")
        self.playwright = await async_playwright().start()
        launch_args = get_launch_args()

        proxy_config = self._parse_proxy(self.proxy) if self.proxy else None

        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=headless,
            viewport=DEFAULT_VIEWPORT,
            args=launch_args,
            permissions=DEFAULT_PERMISSIONS,
            proxy=proxy_config,
        )

        self.page = (
            self.context.pages[0]
            if self.context.pages
            else await self.context.new_page()
        )

        print("正在访问 Gemini...")
        await self.page.goto(
            "https://gemini.google.com/app", wait_until="load", timeout=timeout
        )
        return self.page

    async def close(self):
        """关闭浏览器"""
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
