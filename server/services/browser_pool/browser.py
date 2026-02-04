"""浏览器实例（支持多标签页）"""

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

from core import actions
from core.launcher import GeminiLauncher
from server.core.database import get_db

from . import tasks
from .exceptions import BrowserStatus, NoAvailableTabs, RateLimitExceeded
from .tab import TabInstance


class BrowserInstance:
    """浏览器实例（支持多标签页）"""

    def __init__(
        self,
        browser_id: str,
        account_name: str,
        proxy: Optional[str] = None,
        headless: bool = True,
        user_data_dir: Optional[str] = None,
        rate_limit: int = 3,  # 每分钟请求限制
        rate_window: int = 60,  # 时间窗口（秒）
        max_tabs: int = 3,  # 最大标签页数量
    ):
        self.browser_id = browser_id
        self.account_name = account_name
        self.proxy = proxy
        self.headless = headless
        self.user_data_dir = user_data_dir or f"data/browser_data/{browser_id}"
        self.max_tabs = max_tabs

        # 速率限制配置
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self._request_times: deque = deque()  # 请求时间戳队列

        self.status = BrowserStatus.STOPPED
        self.launcher: Optional[GeminiLauncher] = None  # 浏览器启动器
        self.tabs: List[TabInstance] = []  # 标签页列表
        self.created_at = datetime.now()
        self.last_active_at: Optional[datetime] = None
        self.total_tasks = 0
        self.failed_tasks = 0

    def check_rate_limit(self) -> tuple[bool, Dict]:
        """
        检查当前浏览器是否超过速率限制
        """
        current_time = time.time()

        # 清理过期的请求记录
        while (
            self._request_times
            and self._request_times[0] < current_time - self.rate_window
        ):
            self._request_times.popleft()

        # 检查是否超限
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
        """记录请求"""
        current_time = time.time()
        self._request_times.append(current_time)

    async def start(self):
        """启动浏览器并创建多个标签页"""
        print(f"[Browser {self.browser_id}] Starting with {self.max_tabs} tabs...")
        self.status = BrowserStatus.STARTING

        try:
            # 1. 启动浏览器
            self.launcher = GeminiLauncher(
                account_id=0,
                proxy=self.proxy,
                user_data_dir=self.user_data_dir,
            )
            # 启动并获取第一个 Page
            page0 = await self.launcher.launch(headless=self.headless)
            print(f"[Browser {self.browser_id}] Base browser launched")

            # 2. 初始化标签页列表
            self.tabs = []
            fast_count = self.max_tabs // 2

            # Tab 0: 使用初始页面
            tab0 = TabInstance(
                tab_id=0, browser_id=self.browser_id, preferred_model="Fast"
            )
            tab0.page = page0
            self.tabs.append(tab0)

            # 3. 预热 Tab 0
            print(f"[Browser {self.browser_id}] Preheating Tab 0...")
            tab0_success = await tasks.reinitialize_tab(tab0)
            if not tab0_success:
                print(f"[Browser {self.browser_id}] Tab 0 preheat failed.")
                self.status = BrowserStatus.ERROR
                return

            # 4. 创建并并行预热其他标签页
            if self.max_tabs > 1:
                print(f"[Browser {self.browser_id}] Creating {self.max_tabs - 1} more tabs...")
                
                async def create_and_init_tab(tab_id: int, model: str) -> TabInstance:
                    tab = TabInstance(tab_id, self.browser_id, model)
                    # 创建新页面并访问
                    new_page = await self.launcher.context.new_page()
                    await new_page.goto("https://gemini.google.com/app", wait_until="load")
                    tab.page = new_page
                    await tasks.reinitialize_tab(tab)
                    return tab

                init_tasks = []
                for i in range(1, self.max_tabs):
                    model = "Fast" if i < fast_count else "Pro"
                    init_tasks.append(create_and_init_tab(i, model))
                
                other_tabs = await asyncio.gather(*init_tasks, return_exceptions=True)
                for t in other_tabs:
                    if isinstance(t, TabInstance):
                        self.tabs.append(t)
                    else:
                        print(f"[Browser {self.browser_id}] Tab creation error: {t}")

            self.status = BrowserStatus.IDLE
            self.last_active_at = datetime.now()
            print(f"[Browser {self.browser_id}] Started with {len(self.tabs)} tabs")

            # 记录日志
            try:
                db = get_db()
                await db.add_log("INFO", f"Browser {self.browser_id} started", self.browser_id)
            except:
                pass

        except Exception as e:
            self.status = BrowserStatus.ERROR
            print(f"[Browser {self.browser_id}] Failed to start: {e}")
            raise

    async def stop(self):
        """停止浏览器"""
        print(f"[Browser {self.browser_id}] Stopping...")
        self.status = BrowserStatus.STOPPING
        try:
            if self.launcher:
                await self.launcher.close()
            self.tabs = []
            self.status = BrowserStatus.STOPPED
            print(f"[Browser {self.browser_id}] Stopped")
        except Exception as e:
            print(f"[Browser {self.browser_id}] Stop error: {e}")
            self.status = BrowserStatus.ERROR

    def get_available_tab(self, preferred_model: Optional[str] = None) -> Optional[TabInstance]:
        """获取空闲标签页"""
        idle_tabs = [tab for tab in self.tabs if tab.status == BrowserStatus.IDLE]
        if not idle_tabs:
            return None
        if not preferred_model:
            return idle_tabs[0]
        
        matching = [t for t in idle_tabs if t.preferred_model == preferred_model]
        if matching:
            return sorted(matching, key=lambda t: t.tab_id, reverse=(preferred_model=="Pro"))[0]
        return sorted(idle_tabs, key=lambda t: t.tab_id, reverse=(preferred_model=="Pro"))[0]

    async def execute_task(self, task_id: str, input_image: str, prompt: str, model: str = "Fast"):
        if self.status == BrowserStatus.OFFLINE:
            raise RuntimeError(f"Browser {self.browser_id} is offline")
        
        allowed, info = self.check_rate_limit()
        if not allowed:
            raise RateLimitExceeded(self.browser_id, info["limit"], info["window_seconds"], info["reset"])

        tab = self.get_available_tab(model)
        if not tab:
            raise NoAvailableTabs(self.browser_id, len(self.tabs))

        self.record_request()
        try:
            result = await tasks.execute_task(tab, task_id, input_image, prompt, model)
            if result: self.total_tasks += 1
            else: self.failed_tasks += 1
            return result
        except Exception:
            self.failed_tasks += 1
            raise

    async def execute_fast_task(self, **kwargs):
        if self.status == BrowserStatus.OFFLINE:
            raise RuntimeError(f"Browser {self.browser_id} is offline")
        
        allowed, info = self.check_rate_limit()
        if not allowed:
            raise RateLimitExceeded(self.browser_id, info["limit"], info["window_seconds"], info["reset"])

        tab = self.get_available_tab(kwargs.get("model", "Fast"))
        if not tab:
            raise NoAvailableTabs(self.browser_id, len(self.tabs))

        self.record_request()
        try:
            result = await tasks.execute_fast_task(tab, **kwargs)
            if result: self.total_tasks += 1
            else: self.failed_tasks += 1
            return result
        except Exception:
            self.failed_tasks += 1
            raise

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
