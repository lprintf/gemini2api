"""浏览器实例（支持多标签页） - 纯净资源管理层"""

import asyncio
import random
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
        user_data_dir: Optional[str] = None,
        rate_limit: int = 3,
        rate_window: int = 60,
        max_tabs: int = 3,
    ):
        self.browser_id = browser_id
        self.account_name = account_name
        self.proxy = proxy
        self.user_data_dir = user_data_dir or f"data/browser_data/{browser_id}"
        self.max_tabs = max_tabs

        self.status = BrowserStatus.CLOSED
        self.is_enabled = True # 是否启用（行政状态）
        self.launcher: Optional[GeminiLauncher] = None
        
        # 统计信息
        self.created_at = datetime.now()
        self.last_active_at: Optional[datetime] = None
        self.total_tasks = 0
        self.failed_tasks = 0
        
        # 确保标签页占位符已初始化
        self.tabs: List[TabInstance] = []
        self._ensure_tabs()
        self.created_at = datetime.now()
        self.last_active_at: Optional[datetime] = None
        self.total_tasks = 0
        self.failed_tasks = 0


    def _ensure_tabs(self):
        """确保内部标签页占位符已根据 max_tabs 初始化（非破坏性）"""
        current_count = len(self.tabs)
        if current_count == self.max_tabs:
            return
            
        if current_count < self.max_tabs:
            # 补齐缺少的数量
            fast_count = self.max_tabs // 2
            for i in range(current_count, self.max_tabs):
                model = "Fast" if i < fast_count else "Pro"
                tab = TabInstance(i, self.browser_id, model)
                tab.status = BrowserStatus.CLOSED
                tab.activity = "Closed"
                self.tabs.append(tab)
        else:
            # 数量超出，截断（通常发生在管理员调小了 max_tabs）
            # 注意：这可能会强制关闭正在运行的标签页
            print(f"[Browser {self.browser_id}] Warning: Truncating tabs from {current_count} to {self.max_tabs}")
            self.tabs = self.tabs[:self.max_tabs]

    async def launch(self, on_tab_ready: Optional[Any] = None):
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
            page0 = await self.launcher.launch()

            # 2. 标签页绑定与初始化函数
            async def bind_and_init_tab(tab: TabInstance, page: Page):
                from server.utils.logger import get_tab_logger
                tab.page = page
                
                # 挂载日志和账号上下文
                tab.page._logger = get_tab_logger(self.browser_id, tab.tab_id)
                tab.page._account_name = self.account_name
                
                # 执行环境准备
                tab.status = BrowserStatus.LAUNCHING
                success = await actions.reinitialize_page(page, model=tab.model)
                tab.status = BrowserStatus.IDLE if success else BrowserStatus.ERROR
                
                # 如果初始化成功且提供了回调，立即通知（实现即时入队）
                if success and on_tab_ready:
                    await on_tab_ready(tab)
                    print(f"[Browser {self.browser_id}] Tab {tab.tab_id} ({tab.model}) ready and queued.")

            # 3. 绑定并预热已经预置的 Tab 0
            tab0 = self.tabs[0]
            await bind_and_init_tab(tab0, page0)

            # 4. 如果 Tab 0 没登录/初始化失败，不启动副标签页
            if tab0.status == BrowserStatus.ERROR:
                print(f"[Browser {self.browser_id}] Main tab failed to initialize. Skipping additional tabs.")
                self.status = BrowserStatus.ERROR
                return

            # 5. 并行启动其它 Tab
            if self.max_tabs > 1:

                async def setup_tab(tab: TabInstance, index: int) -> bool:
                    await asyncio.sleep(index * random.uniform(1.0, 5.0))
                    try:
                        new_page = await self.launcher.context.new_page()
                        await bind_and_init_tab(tab, new_page)
                        return True
                    except Exception as e:
                        tab.status = BrowserStatus.ERROR
                        print(f"[Browser {self.browser_id}] Init Tab {tab.tab_id} Fail: {e}")
                        return False

                init_tasks = [setup_tab(self.tabs[i], i) for i in range(1, self.max_tabs)]
                await asyncio.gather(*init_tasks)

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
                self.launcher = None
                
            # 重置所有标签页状态，但不删除对象（防止 launch 时的 IndexError）
            for tab in self.tabs:
                tab.page = None
                tab.status = BrowserStatus.CLOSED
                tab.activity = "Closed"
                
            self.status = BrowserStatus.CLOSED
        except:
            self.status = BrowserStatus.ERROR

    def get_busy_tabs_count(self) -> int:
        """获取忙碌标签页数量"""
        return sum(1 for t in self.tabs if t.status == BrowserStatus.BUSY)

    def to_dict(self) -> Dict:
        # 导出状态：如果物理状态是 IDLE 但没有空闲 Tab，则对外表现为 BUSY
        display_status = self.status.value
        if self.status == BrowserStatus.IDLE:
            idle_tabs_count = sum(1 for t in self.tabs if t.status == BrowserStatus.IDLE)
            if idle_tabs_count == 0 and len(self.tabs) > 0:
                display_status = BrowserStatus.BUSY.value

        return {
            "browser_id": self.browser_id,
            "status": display_status,
            "total_tasks": self.total_tasks,
            "failed_tasks": self.failed_tasks,
            "total_tabs": len(self.tabs),
            "idle_tabs": sum(1 for t in self.tabs if t.status == BrowserStatus.IDLE),
            "sleeping_tabs": sum(1 for t in self.tabs if t.status == BrowserStatus.SLEEP),
            "rate_limit": {"remaining": 999, "limit": 999}, # 兼容性占位
            "account_name": self.account_name,
            "proxy": self.proxy,
            "max_tabs": self.max_tabs,
            "is_enabled": self.is_enabled,
            "tabs": [t.to_dict() for t in self.tabs]
        }
