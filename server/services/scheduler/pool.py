"""浏览器池管理器"""

import asyncio
import random
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
    ):
        self.browsers: Dict[str, BrowserInstance] = {}
        self.min_browsers = min_browsers
        self.max_browsers = max_browsers
        self._lock = asyncio.Lock()
        self._next_id = 0  # 自增 ID 计数器
        
        # O(1) 调度队列: 模型 -> 异步队列 (存储 TabInstance)
        self._idle_queues = {
            "Fast": asyncio.Queue(),
            "Pro": asyncio.Queue()
        }

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
                    user_data_dir=config.user_data_dir,
                    max_tabs=config.max_tabs,
                )
                if config.is_enabled is not None:
                    browser.is_enabled = config.is_enabled
                
                # 如果状态记录为 DISABLED，则转换为 IDLE（功能状态与管理状态已分离）
                if browser.status == BrowserStatus.DISABLED:
                    browser.status = BrowserStatus.IDLE
                
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

            # 随机打乱启动顺序，防止每次重启都是固定几个 ID 的浏览器先入队
            random.shuffle(auto_start_browsers)

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
                # 传入 release_tab 作为回调，使标签页一旦就绪（即使物理浏览器还没完全启动完其它标签）就立刻入队
                await browser.launch(on_tab_ready=self.release_tab)
                return (browser.browser_id, True, "")
            except Exception as e:
                return (browser.browser_id, False, str(e))

        async def start_with_delay(b, delay):
            if delay > 0:
                await asyncio.sleep(delay)
            return await start_browser_safe(b)

        start_time = time.time()
        
        # 记录启动任务的引用，防止被 GC
        self._startup_tasks = []

        async def run_startup_sequence(b, delay):
            if delay > 0:
                await asyncio.sleep(delay)
            browser_id, success, error_msg = await start_browser_safe(b)
            if success:
                # 状态已由 BrowserInstance 内部的 Tab 实时上报，此处仅记录浏览器核心就绪
                pass 
                if browser_id in disabled_after_start:
                    print(f"[BrowserPool] Browser {browser_id} is disabled.")
            else:
                print(f"[BrowserPool] Failed to start browser {browser_id}: {error_msg}")
                await db.add_log("ERROR", f"Failed to load browser {browser_id}: {error_msg}", browser_id)

        for i, b in enumerate(browsers_to_start):
            task = asyncio.create_task(run_startup_sequence(b, i * random.uniform(0.1, 3.0)))
            self._startup_tasks.append(task)

        print(f"[BrowserPool] Initiated background startup for {len(browsers_to_start)} browsers.")
        await db.add_log("INFO", f"Initiated background startup for {len(browsers_to_start)} browsers.")

        # 整理工作：Tab 已在 start_browser_safe 中实时入队



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
                    user_data_dir=user_data_dir,
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
                user_data_dir=user_data_dir,
                max_tabs=max_tabs,
            )
            browser.is_enabled = is_enabled

            self.browsers[browser_id_str] = browser

            if auto_start:
                # 异步启动，不阻塞 API
                asyncio.create_task(browser.launch(on_tab_ready=self.release_tab))

            print(
                f"[BrowserPool] Created browser {browser_id_str} (account: {account_name}, tabs: {max_tabs}, dir: {user_data_dir})"
            )
            return browser_id_str
            
    async def acquire_tab(self, model: str = "Fast", timeout: Optional[float] = 0) -> "TabInstance":
        """获取一个可用标签页 (支持超时)"""
        from ..objects.exceptions import NoAvailableBrowsers
        
        if model not in self._idle_queues:
            raise ValueError(f"Model {model} not found in browser pool")
            
        try:
            if timeout == 0:
                # 立即获取，不阻塞
                return self._idle_queues[model].get_nowait()
            elif timeout is not None:
                # 阻塞等待直至超时
                return await asyncio.wait_for(self._idle_queues[model].get(), timeout=timeout)
            else:
                # 永久阻塞等待
                return await self._idle_queues[model].get()
        except (asyncio.QueueEmpty, asyncio.TimeoutError):
            raise NoAvailableBrowsers()

    async def release_tab(self, tab: "TabInstance"):
        """将标签页还回对应模型的空闲队列"""
        if tab.status != BrowserStatus.IDLE:
            # 如果不是 IDLE 状态（如处于 SLEEP），则不进入队列
            return

        # 放入队尾，实现 FIFO 天然轮换
        await self._idle_queues[tab.model].put(tab)

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
            if "is_enabled" in updates:
                # 只在数据库记录中标记启用/禁用，不修改内存中的 status 状态
                # 状态指示灯仅反映功能状态（Error, Busy, Idle, Sleep 等）
                browser.is_enabled = updates["is_enabled"]
            if "max_tabs" in updates:
                new_max = int(updates["max_tabs"])
                if new_max > 0:
                    browser.max_tabs = new_max
                    browser._ensure_tabs()

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
            # 从内存中移除，这样其它请求就不会再看到它
            del self.browsers[browser_id]

            # 异步关闭浏览器，不占锁
            asyncio.create_task(browser.close())

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

        # 异步启动，不阻塞 API
        asyncio.create_task(browser.launch(on_tab_ready=self.release_tab))

    async def close_browser(self, browser_id: str):
        """停止指定浏览器"""
        if browser_id not in self.browsers:
            raise KeyError(f"Browser {browser_id} not found")

        browser = self.browsers[browser_id]
        if browser.status == BrowserStatus.CLOSED:
            raise RuntimeError(f"Browser {browser_id} is already closed")

        # 异步关闭，不阻塞 API
        asyncio.create_task(browser.close())

    def get_browser(self, browser_id: str) -> Optional[BrowserInstance]:
        """获取指定浏览器"""
        return self.browsers.get(browser_id)

    def get_status(self) -> Dict:
        """获取浏览器池状态"""
        browsers_dicts = [b.to_dict() for b in self.browsers.values()]
        
        status_count = {}
        for status in BrowserStatus:
            status_count[status.value] = 0
            
        for b_dict in browsers_dicts:
            status = b_dict["status"]
            status_count[status] = status_count.get(status, 0) + 1

        return {
            "total_browsers": len(self.browsers),
            "status_count": status_count,
            "browsers": browsers_dicts,
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
