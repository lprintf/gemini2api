"""浏览器池管理器"""

import asyncio

import time
from datetime import datetime
from typing import Dict, Optional

from server.db.database import get_db
from server.db.models import BrowserConfig, TaskRecord

from ..objects.browser import BrowserInstance
from ..objects.exceptions import BrowserStatus


class BrowserPool:
    """浏览器池管理器"""

    def __init__(
        self,
        min_browsers: int = 1,
        max_browsers: int = 20,
        browser_rate_limit: int = 3,  # 每个浏览器的速率限制
        browser_rate_window: int = 60,  # 速率限制时间窗口
    ):
        self.browsers: Dict[str, BrowserInstance] = {}
        self.min_browsers = min_browsers
        self.max_browsers = max_browsers
        self.browser_rate_limit = browser_rate_limit
        self.browser_rate_window = browser_rate_window
        self._lock = asyncio.Lock()
        self._next_id = 0  # 自增 ID 计数器

    async def load_from_db(self):
        """从数据库加载所有浏览器配置（后台并行启动自动启动的浏览器）"""
        try:
            db = get_db()

            # 获取下一个可用 ID
            self._next_id = await db.get_next_browser_id()

            # 获取所有浏览器配置（包括 disabled 的）
            all_configs = await db.get_all_browsers()

            print(f"[BrowserPool] Loading {len(all_configs)} browsers from database...")

            if not all_configs:
                await db.add_log("INFO", "Browser pool loaded 0 browsers")
                return

            # 分类：需要自动启动的 vs 只需要注册的
            auto_start_browsers = []
            disabled_after_start = []  # 启动后需要标记为 disabled 的

            for config in all_configs:
                browser = BrowserInstance(
                    browser_id=config.browser_id,
                    account_name=config.account_name,
                    proxy=config.proxy,
                    headless=config.headless,
                    user_data_dir=config.user_data_dir,
                    rate_limit=config.rate_limit,
                    rate_window=config.rate_window,
                )
                
                self.browsers[config.browser_id] = browser
                
                # 根据配置决定是否自动启动
                if config.auto_start:
                    auto_start_browsers.append(browser)
                    # disabled 的浏览器也会启动，但启动后标记为 DISABLED（不接受任务）
                    if not config.is_enabled:
                        disabled_after_start.append(browser.browser_id)
                else:
                    # 不自动启动的浏览器直接标记为 CLOSED
                    browser.status = BrowserStatus.CLOSED

            print(f"[BrowserPool] {len(auto_start_browsers)} browsers marked for auto-start")

            # 后台并行启动需要自动启动的浏览器
            if auto_start_browsers:
                asyncio.create_task(self._start_browsers_background(auto_start_browsers, disabled_after_start))


        except Exception as e:
            print(f"[BrowserPool] Failed to load from database: {e}")


    async def _start_browsers_background(self, browsers_to_start: list, disabled_after_start: list = None):
        """后台并行启动指定的浏览器"""
        db = get_db()
        disabled_after_start = disabled_after_start or []

        async def start_browser_safe(browser: BrowserInstance) -> tuple[str, bool, str]:
            """安全启动单个浏览器，返回 (browser_id, success, error_msg)"""
            try:
                await browser.launch()
                return (browser.browser_id, True, "")
            except Exception as e:
                return (browser.browser_id, False, str(e))

        print(f"[BrowserPool] Starting {len(browsers_to_start)} browsers in background...")
        start_time = time.time()

        results = await asyncio.gather(
            *[start_browser_safe(b) for b in browsers_to_start]
        )

        # 处理启动结果
        success_count = 0
        for browser_id, success, error_msg in results:
            if success:
                success_count += 1
                print(f"[BrowserPool] Browser {browser_id} started successfully")
                # 如果是 disabled 的浏览器，启动后标记为 DISABLED（不接受任务调度）
                if browser_id in disabled_after_start:
                    self.browsers[browser_id].status = BrowserStatus.DISABLED
                    print(f"[BrowserPool] Browser {browser_id} marked as DISABLED")
            else:
                print(
                    f"[BrowserPool] Failed to start browser {browser_id}: {error_msg}"
                )
                await db.add_log(
                    "ERROR",
                    f"Failed to load browser {browser_id}: {error_msg}",
                    browser_id,
                )

        elapsed = time.time() - start_time
        print(
            f"[BrowserPool] Background startup completed: {success_count}/{len(browsers_to_start)} "
            f"browsers in {elapsed:.2f}s"
        )

        await db.add_log(
            "INFO",
            f"Browser pool loaded {success_count}/{len(browsers_to_start)} browsers in {elapsed:.2f}s",
        )



    async def create_browser(
        self,
        browser_id: Optional[int] = None,  # 可选的浏览器 ID
        account_name: Optional[str] = None,  # 可选的账号名称
        proxy: Optional[str] = None,
        headless: bool = True,
        auto_start: bool = True,
        is_enabled: bool = True,
        max_tabs: int = 3,  # 最大标签页数量
    ) -> str:
        """创建新浏览器实例"""
        async with self._lock:
            if len(self.browsers) >= self.max_browsers:
                raise RuntimeError(f"Browser pool is full (max: {self.max_browsers})")

            # 确定 browser_id
            if browser_id is None:
                # 自动分配 ID
                browser_id = self._next_id
                self._next_id += 1
            else:
                # 使用指定的 ID，并更新计数器
                if browser_id >= self._next_id:
                    self._next_id = browser_id + 1

            # 确定 account_name（默认等于 ID）
            if account_name is None:
                account_name = str(browser_id)

            # browser_id 字符串（用于内部标识）
            browser_id_str = str(browser_id)

            # 检查 ID 是否已存在
            if browser_id_str in self.browsers:
                raise RuntimeError(f"Browser ID {browser_id} already exists")

            # user_data_dir 使用 ID
            user_data_dir = f"data/browser_data/{browser_id}"

            # 保存到数据库
            try:
                db = get_db()
                config = BrowserConfig(
                    browser_id=browser_id_str,
                    account_name=account_name,
                    proxy=proxy,
                    headless=headless,
                    user_data_dir=user_data_dir,
                    rate_limit=self.browser_rate_limit,
                    rate_window=self.browser_rate_window,
                    is_enabled=is_enabled,
                    auto_start=auto_start,
                )
                await db.create_browser(config)
                await db.add_log(
                    "INFO",
                    f"Browser {browser_id_str} created with {max_tabs} tabs",
                    browser_id_str,
                )
            except Exception as e:
                print(f"[BrowserPool] Failed to save browser to database: {e}")
                # 继续创建实例，即使数据库保存失败

            browser = BrowserInstance(
                browser_id=browser_id_str,
                account_name=account_name,
                proxy=proxy,
                headless=headless,
                rate_limit=self.browser_rate_limit,
                rate_window=self.browser_rate_window,
                user_data_dir=user_data_dir,
                max_tabs=max_tabs,
            )

            self.browsers[browser_id_str] = browser

            if auto_start:
                await browser.launch()

            print(
                f"[BrowserPool] Created browser {browser_id_str} (account: {account_name}, tabs: {max_tabs}, dir: {user_data_dir})"
            )
            return browser_id_str

    async def update_browser(
        self, browser_id: str, updates: Dict
    ) -> Optional[BrowserInstance]:
        """更新浏览器配置"""
        async with self._lock:
            if browser_id not in self.browsers:
                raise KeyError(f"Browser {browser_id} not found")

            browser = self.browsers[browser_id]

            # 更新内存中的配置
            if "account_name" in updates:
                browser.account_name = updates["account_name"]
            if "proxy" in updates:
                browser.proxy = updates["proxy"]
            if "headless" in updates:
                browser.headless = updates["headless"]
            if "rate_limit" in updates:
                browser.rate_limit = updates["rate_limit"]
            if "rate_window" in updates:
                browser.rate_window = updates["rate_window"]
            if "is_enabled" in updates:
                is_enabled = updates["is_enabled"]
                if not is_enabled:
                    # 如果禁用，且当前是空闲或错误状态，则设置为 DISABLED
                    if browser.status in (BrowserStatus.IDLE, BrowserStatus.ERROR):
                        browser.status = BrowserStatus.DISABLED
                else:
                    # 如果重新启用，且当前是 DISABLED 状态，则回退到 IDLE
                    if browser.status == BrowserStatus.DISABLED:
                        browser.status = BrowserStatus.IDLE

            # 更新数据库
            try:
                db = get_db()
                await db.update_browser(browser_id, updates)
                await db.add_log(
                    "INFO", f"Browser {browser_id} updated: {updates}", browser_id
                )
            except Exception as e:
                print(f"[BrowserPool] Failed to update browser in database: {e}")

            return browser

    async def remove_browser(self, browser_id: str):
        """删除浏览器"""
        async with self._lock:
            if browser_id not in self.browsers:
                raise KeyError(f"Browser {browser_id} not found")

            browser = self.browsers[browser_id]
            await browser.close()
            del self.browsers[browser_id]

            # 从数据库删除
            try:
                db = get_db()
                await db.delete_browser(browser_id)
                await db.add_log("INFO", f"Browser {browser_id} removed", browser_id)
            except Exception as e:
                print(f"[BrowserPool] Failed to delete browser from database: {e}")

            print(f"[BrowserPool] Removed browser {browser_id}")

    async def launch_browser(self, browser_id: str):
        """启动指定浏览器"""
        if browser_id not in self.browsers:
            raise KeyError(f"Browser {browser_id} not found")

        browser = self.browsers[browser_id]
        if browser.status != BrowserStatus.CLOSED:
            raise RuntimeError(
                f"Browser {browser_id} is not closed (status: {browser.status})"
            )

        await browser.launch()

    async def close_browser(self, browser_id: str):
        """停止指定浏览器"""
        if browser_id not in self.browsers:
            raise KeyError(f"Browser {browser_id} not found")

        browser = self.browsers[browser_id]
        if browser.status == BrowserStatus.CLOSED:
            raise RuntimeError(f"Browser {browser_id} is already closed")

        await browser.close()

    async def get_available_browser(
        self, preferred_model: Optional[str] = None
    ) -> Optional[BrowserInstance]:
        """
        获取可用的浏览器（负载均衡）

        排序优先级：空闲Tab多 > rate_limit剩余多 > 失败少 > 任务轻
        """
        available = [
            b for b in self.browsers.values()
            if b.status == BrowserStatus.IDLE
            and b.get_available_tab(preferred_model) is not None
        ]

        if not available:
            return None

        def sort_key(b: BrowserInstance):
            idle_tabs = sum(1 for t in b.tabs if t.status == BrowserStatus.IDLE)
            _, rate_info = b.check_rate_limit()
            tab = b.get_available_tab(preferred_model)
            tab_tasks = tab.total_tasks if tab else float("inf")
            return (-idle_tabs, -rate_info["remaining"], b.failed_tasks, tab_tasks)

        available.sort(key=sort_key)
        return available[0]

    def get_browser(self, browser_id: str) -> Optional[BrowserInstance]:
        """获取指定浏览器"""
        return self.browsers.get(browser_id)

    def get_status(self) -> Dict:
        """获取浏览器池状态"""
        status_count = {}
        for status in BrowserStatus:
            count = sum(1 for b in self.browsers.values() if b.status == status)
            status_count[status.value] = count

        return {
            "total_browsers": len(self.browsers),
            "status_count": status_count,
            "browsers": [browser.to_dict() for browser in self.browsers.values()],
            "total_tasks": sum(b.total_tasks for b in self.browsers.values()),
            "failed_tasks": sum(b.failed_tasks for b in self.browsers.values()),
        }

    async def create_task_record(
        self, task_id: str, prompt: str, model: str, input_image: Optional[str] = None
    ) -> TaskRecord:
        """创建任务记录"""
        task = TaskRecord(
            task_id=task_id,
            prompt=prompt,
            model=model,
            input_image=input_image,
            status="pending",
            created_at=datetime.now(),
        )

        try:
            db = get_db()
            await db.create_task(task)
        except Exception as e:
            print(f"[BrowserPool] Failed to create task record: {e}")

        return task

    async def shutdown(self):
        """关闭所有浏览器"""
        print("[BrowserPool] Shutting down...")

        try:
            db = get_db()
            await db.add_log("INFO", "Browser pool shutting down")
        except Exception:
            pass

        tasks = [browser.close() for browser in self.browsers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self.browsers.clear()
        print("[BrowserPool] All browsers stopped")
