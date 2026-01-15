"""
Gemini Browser Manager - 管理Gemini浏览器会话

支持功能：
- 多账户管理（使用数字编号区分不同账户）
- 首次手动登录并保存浏览器状态
- 后续使用保存的状态自动登录
- 支持headless模式用于生产环境
- 支持GUI模式用于开发测试

用法：
    python gemini_browser.py login [账户编号]              # 首次手动登录并保存
    python gemini_browser.py run [账户编号] [--headless]   # 运行浏览器会话
    python gemini_browser.py list                          # 列出所有已保存的账户

示例：
    # 开发测试（带GUI）
    python gemini_browser.py login 0        # 设置账户0
    python gemini_browser.py run 0          # 使用账户0运行（GUI模式）

    # 生产环境（无头模式）
    python gemini_browser.py run 0 --headless   # 使用账户0运行（无头模式）

    # 账户管理
    python gemini_browser.py list           # 列出所有账户
"""

import asyncio
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from .browser import DEFAULT_PERMISSIONS, DEFAULT_VIEWPORT, get_launch_args


class GeminiBrowser:
    """Gemini浏览器管理器"""

    def __init__(
        self,
        account_id: int = 0,
        headless: bool = False,
        proxy: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
    ):
        self.account_id = account_id
        self.headless = headless
        self.proxy = proxy  # 例如: "http://10.42.0.1:20171"
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

    async def setup_login(self):
        """首次登录设置 - 打开浏览器让用户手动登录"""
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        print("=" * 60)
        print(f"首次登录设置 - 账户 {self.account_id}")
        print("=" * 60)
        print(f"数据目录: {self.user_data_dir}")

        async with async_playwright() as p:
            # 检测是否在 Wayland 环境
            import os

            wayland_display = os.environ.get("WAYLAND_DISPLAY")

            browser_args = [
                "--disable-blink-features=AutomationControlled",
            ]

            # 如果是 Wayland 环境，添加 ozone 平台参数
            if wayland_display:
                browser_args.extend(
                    [
                        "--ozone-platform=wayland",
                        "--enable-features=UseOzonePlatform",
                    ]
                )

            # 使用持久化上下文（必须是GUI模式）
            context = await p.chromium.launch_persistent_context(
                str(self.user_data_dir),
                headless=False,  # 登录必须是GUI模式
                viewport={"width": 1280, "height": 900},
                args=browser_args,
            )

            page = context.pages[0] if context.pages else await context.new_page()

            print("\n步骤:")
            print("1. 浏览器已打开，请手动登录 Google")
            print("2. 访问 https://gemini.google.com")
            print("3. 确认可以正常使用Gemini")
            print("4. 完成后在终端按 Enter 键保存状态\n")

            # 打开Gemini页面
            await page.goto("https://gemini.google.com")

            # 等待用户确认
            input("按 Enter 键保存登录状态...")

            # 保存cookies
            await self._save_cookies(context)

            print(f"\n✓ 账户 {self.account_id} 的浏览器状态已保存")
            print(f"\n下次运行: python gemini_browser.py run {self.account_id}")

            await context.close()

    async def _save_cookies(self, context: BrowserContext):
        """保存cookies到文件"""
        cookies = await context.cookies()

        # 保存完整cookies
        cookies_file = self.user_data_dir / "cookies.json"
        with open(cookies_file, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2)
        print(f"\n✓ 已保存 {len(cookies)} 个cookies到: {cookies_file}")

        # 提取并保存重要的Google cookies
        google_cookies = [c for c in cookies if "google.com" in c.get("domain", "")]
        print(f"✓ 其中Google相关cookies: {len(google_cookies)} 个")

        important = {}
        for cookie in google_cookies:
            name = cookie["name"]
            if name in [
                "__Secure-1PSID",
                "__Secure-3PSID",
                "SAPISID",
                "__Secure-1PSIDTS",
                "SID",
                "HSID",
                "SSID",
                "APISID",
            ]:
                important[name] = cookie["value"]

        if important:
            env_file = self.user_data_dir / f".env.account{self.account_id}"
            with open(env_file, "w", encoding="utf-8") as f:
                f.write(f"# Google认证cookies - 账户 {self.account_id}\n")
                for key, value in important.items():
                    f.write(f'{key}="{value}"\n')
            print(f"✓ 重要cookies已保存到: {env_file}")

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

        mode = "无头模式" if self.headless else "GUI模式"
        print("=" * 60)
        print(f"启动Gemini浏览器 - 账户 {self.account_id} ({mode})")
        print("=" * 60)
        print(f"数据目录: {self.user_data_dir}")

        # 创建playwright实例并保持
        self.playwright = await async_playwright().start()

        # 使用统一的启动参数配置
        launch_args = get_launch_args(headless=self.headless, proxy=self.proxy)

        if self.proxy:
            print(f"使用代理: {self.proxy}")

        # 使用保存的持久化上下文
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=self.headless,
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

    async def run_demo(self, duration: int = 20):
        """
        演示运行 - 启动浏览器并保持一段时间

        Args:
            duration: 运行时长（秒）
        """
        try:
            page = await self.launch()

            # 截图
            if not self.headless:
                screenshot_path = (
                    self.base_dir / "test" / f"session_account{self.account_id}.png"
                )
                screenshot_path.parent.mkdir(exist_ok=True)
                await page.screenshot(path=str(screenshot_path), full_page=True)
                print(f"  截图: {screenshot_path}")

            # 等待
            print(f"\n运行 {duration} 秒...")
            await asyncio.sleep(duration)

        finally:
            await self.close()


def list_accounts():
    """列出所有已保存的账户"""
    # 数据目录：优先使用 /app/data，否则使用代码目录
    data_dir = (
        Path("/app/data") if Path("/app/data").exists() else Path(__file__).parent
    )
    browser_data_dir = data_dir / "browser_data"

    if not browser_data_dir.exists():
        print("❌ 没有找到任何已保存的账户")
        print("请先运行: python gemini_browser.py login 0")
        return

    accounts = []
    for item in browser_data_dir.iterdir():
        if item.is_dir() and item.name.isdigit():
            account_id = int(item.name)
            cookies_file = item / "cookies.json"
            env_file = item / f".env.account{account_id}"

            info = {
                "id": account_id,
                "path": item,
                "has_cookies": cookies_file.exists(),
                "has_env": env_file.exists(),
            }

            # 读取cookies信息
            if cookies_file.exists():
                try:
                    with open(cookies_file, encoding="utf-8") as f:
                        cookies = json.load(f)
                        info["cookies_count"] = len(cookies)
                except Exception:
                    info["cookies_count"] = 0

            accounts.append(info)

    if not accounts:
        print("❌ 没有找到任何已保存的账户")
        print("请先运行: python gemini_browser.py login 0")
        return

    accounts.sort(key=lambda x: x["id"])

    print("=" * 60)
    print("已保存的账户列表")
    print("=" * 60)
    print()

    for acc in accounts:
        print(f"账户 {acc['id']}:")
        print(f"  路径: {acc['path']}")
        print(f"  Cookies: {'✓' if acc['has_cookies'] else '✗'}", end="")
        if acc.get("cookies_count"):
            print(f" ({acc['cookies_count']} 个)")
        else:
            print()
        print(f"  环境变量: {'✓' if acc['has_env'] else '✗'}")
        print()

    print(f"总计: {len(accounts)} 个账户")
    print()
    print("使用方法:")
    print("  python gemini_browser.py run 0           # GUI模式")
    print("  python gemini_browser.py run 0 --headless # 无头模式")


def show_help():
    """显示帮助信息"""
    print(__doc__)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        # 列出所有账户
        list_accounts()

    elif command == "login":
        # 登录模式
        account_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        browser = GeminiBrowser(account_id)
        asyncio.run(browser.setup_login())

    elif command == "run":
        # 运行模式
        if len(sys.argv) < 3:
            print("❌ 缺少账户编号")
            print("用法: python gemini_browser.py run <账户编号> [--headless]")
            sys.exit(1)

        account_id = int(sys.argv[2])
        headless = "--headless" in sys.argv

        browser = GeminiBrowser(account_id, headless=headless)
        asyncio.run(browser.run_demo())

    elif command in ["help", "--help", "-h"]:
        show_help()

    else:
        print(f"❌ 未知命令: {command}")
        print()
        show_help()
        sys.exit(1)
