"""浏览器实例（支持多标签页） - 纯净资源管理层"""

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional
from playwright.async_api import Page

from server.services.tasks import actions
from .launcher import GeminiLauncher
from server.db.database import get_db

from .exceptions import BrowserStatus, NoAvailableTabs, RateLimitExceeded
from .tab import TabInstance


class BrowserInstance:
    """浏览器实例：管理物理浏览器和多个标签页资源的生命周期"""

    def __init__(
        self,
        browser_id: str,
        account_name: str,
        proxy: Optional[str] = None,
        headless: bool = True,
        user_data_dir: Optional[str] = None,
        rate_limit: int = 3,
        rate_window: int = 60,
        max_tabs: int = 3,
    ):
        self.browser_id = browser_id
        self.account_name = account_name
        self.proxy = proxy
        self.headless = headless
        self.user_data_dir = user_data_dir or f"data/browser_data/{browser_id}"
        self.max_tabs = max_tabs

        # 速率限制
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self._request_times: deque = deque()

        self.status = BrowserStatus.CLOSED
        self.launcher: Optional[GeminiLauncher] = None
        self.tabs: List[TabInstance] = []
        
        # 统计信息
        self.created_at = datetime.now()
        self.last_active_at: Optional[datetime] = None
        self.total_tasks = 0
        self.failed_tasks = 0

    def check_rate_limit(self) -> tuple[bool, Dict]:
        """检查速率限制"""
        current_time = time.time()
        while self._request_times and self._request_times[0] < current_time - self.rate_window:
            self._request_times.popleft()
        
        remaining = self.rate_limit - len(self._request_times)
        allowed = remaining > 0
        info = {
            "limit": self.rate_limit,
            "remaining": max(0, remaining),
            "reset": int(current_time + self.rate_window) if not allowed else None,
            "window_seconds": self.rate_window,
        }
        return allowed, info

    def record_request(self):
        self._request_times.append(time.time())

    async def launch(self):
        """核心启动逻辑：初始化物理浏览器并并行预热标签页"""
        print(f"[Browser {self.browser_id}] Starting Resource...")
        self.status = BrowserStatus.LAUNCHING

        try:
            # 1. 物理启动
            self.launcher = GeminiLauncher(
                account_id=0, # 内部使用账户目录
                proxy=self.proxy,
                user_data_dir=self.user_data_dir,
            )
            page0 = await self.launcher.launch(headless=self.headless)

            # 2. 标签页初始化函数 (封装内部逻辑，避免依赖外部 Task)
            async def init_tab_resource(tab_id: int, page: Page, model: str) -> TabInstance:
                tab = TabInstance(tab_id, self.browser_id, model)
                tab.page = page
                # 直接调用 Action 原子步进行环境准备
                success = await actions.reinitialize_page(page, model=model)
                tab.status = BrowserStatus.IDLE if success else BrowserStatus.ERROR
                return tab

            # 3. 预热 Tab 0
            tab0 = await init_tab_resource(0, page0, "Fast")
            self.tabs = [tab0]

            # 4. 如果 Tab 0 没登录/初始化失败，不启动副标签页
            if tab0.status == BrowserStatus.ERROR:
                print(f"[Browser {self.browser_id}] Main tab failed to initialize. Skipping additional tabs.")
                self.status = BrowserStatus.ERROR
                return

            # 5. 并行启动其它 Tab
            if self.max_tabs > 1:

                fast_count = self.max_tabs // 2
                
                async def create_new_tab(tab_id: int) -> TabInstance:
                    model = "Fast" if tab_id < fast_count else "Pro"
                    new_page = await self.launcher.context.new_page()
                    return await init_tab_resource(tab_id, new_page, model)

                init_tasks = [create_new_tab(i) for i in range(1, self.max_tabs)]
                other_tabs = await asyncio.gather(*init_tasks, return_exceptions=True)
                
                for t in other_tabs:
                    if isinstance(t, TabInstance):
                        self.tabs.append(t)
                    else:
                        print(f"[Browser {self.browser_id}] Init Tab Fail: {t}")

            self.status = BrowserStatus.IDLE
            self.last_active_at = datetime.now()
            print(f"[Browser {self.browser_id}] Ready.")

        except Exception as e:
            self.status = BrowserStatus.ERROR
            print(f"[Browser {self.browser_id}] Start Fail: {e}")
            raise

    async def close(self):
        """释放资源"""
        self.status = BrowserStatus.CLOSING
        try:
            if self.launcher:
                await self.launcher.close()
            self.tabs = []
            self.status = BrowserStatus.CLOSED
        except:
            self.status = BrowserStatus.ERROR

    def get_busy_tabs_count(self) -> int:
        """获取忙碌标签页数量"""
        return sum(1 for t in self.tabs if t.status == BrowserStatus.BUSY)

    def get_available_tab(self, preferred_model: Optional[str] = None) -> Optional[TabInstance]:
        """寻找可用标签页"""
        # 只要是 IDLE 状态的都可以被 Scheduler 调度
        idles = [t for t in self.tabs if t.status == BrowserStatus.IDLE]
        if not idles: return None
        
        # 优先匹配模型
        if preferred_model:
            match = [t for t in idles if t.preferred_model == preferred_model]
            if match: return match[0]
            
        return idles[0]

    def to_dict(self) -> Dict:
        _, rate_info = self.check_rate_limit()
        return {
            "browser_id": self.browser_id,
            "status": self.status.value,
            "total_tasks": self.total_tasks,
            "failed_tasks": self.failed_tasks,
            "total_tabs": len(self.tabs),
            "idle_tabs": sum(1 for t in self.tabs if t.status == BrowserStatus.IDLE),
            "rate_limit": rate_info,
            "account_name": self.account_name,
            "proxy": self.proxy,
            "max_tabs": self.max_tabs,
        }
