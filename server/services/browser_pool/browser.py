"""浏览器实例（支持多标签页）"""

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.editor import GeminiEditor
from server.core.database import get_db

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
        self.base_editor: Optional[GeminiEditor] = None  # 主编辑器（用于创建标签页）
        self.tabs: List[TabInstance] = []  # 标签页列表
        self.created_at = datetime.now()
        self.last_active_at: Optional[datetime] = None
        self.total_tasks = 0
        self.failed_tasks = 0

    def check_rate_limit(self) -> tuple[bool, Dict]:
        """
        检查当前浏览器是否超过速率限制

        Returns:
            (是否允许, 限制信息)
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
        """启动浏览器并创建多个标签页

        流程：
        1. 启动浏览器，创建第一个标签页
        2. 预热第一个标签页（必须成功）
        3. 如果成功，继续创建和预热其他标签页
        4. 如果失败，停止并设置为 ERROR 状态，等待用户手动处理
        """
        print(f"[Browser {self.browser_id}] Starting with {self.max_tabs} tabs...")
        self.status = BrowserStatus.STARTING

        try:
            # 创建主编辑器
            self.base_editor = GeminiEditor(
                account_id=0,
                proxy=self.proxy,
                enable_logging=False,
                user_data_dir=self.user_data_dir,
            )

            # 启动浏览器
            await self.base_editor.launch()
            print(f"[Browser {self.browser_id}] Base browser launched")

            # 创建标签页列表
            self.tabs = []

            # 计算标签页分配策略：一半 Pro，一半 Fast
            fast_count = self.max_tabs // 2
            # pro_count = self.max_tabs - fast_count

            # Tab 0: 使用主编辑器（Fast 模型）
            tab0 = TabInstance(
                tab_id=0, browser_id=self.browser_id, preferred_model="Fast"
            )
            tab0.editor = self.base_editor
            self.tabs.append(tab0)
            print(f"[Browser {self.browser_id}] Tab 0 created (preferred: Fast)")

            # 预热第一个标签页（必须成功才能继续）
            print(f"[Browser {self.browser_id}] Preheating Tab 0...")
            tab0.status = BrowserStatus.PREHEATING
            tab0_start = time.time()

            try:
                tab0_success = await tab0.editor.prepare_environment(
                    model=tab0.preferred_model,
                    temporary_chat=False,
                )
                tab0_elapsed = time.time() - tab0_start

                if not tab0_success:
                    print(
                        f"[Browser {self.browser_id}] Tab 0 preheat FAILED ({tab0_elapsed:.3f}s). "
                        f"Please check login status and restart manually."
                    )
                    self.status = BrowserStatus.ERROR
                    tab0.status = BrowserStatus.ERROR

                    try:
                        db = get_db()
                        await db.add_log(
                            "ERROR",
                            f"Browser {self.browser_id} Tab 0 preheat failed. Manual intervention required.",
                            self.browser_id,
                        )
                    except Exception:
                        pass
                    return  # 不抛出异常，让浏览器保持打开状态供用户检查

                tab0.status = BrowserStatus.IDLE
                print(
                    f"[Browser {self.browser_id}] Tab 0 preheated successfully ({tab0_elapsed:.3f}s)"
                )

            except Exception as e:
                tab0_elapsed = time.time() - tab0_start
                print(
                    f"[Browser {self.browser_id}] Tab 0 preheat ERROR ({tab0_elapsed:.3f}s): {e}. "
                    f"Please check and restart manually."
                )
                self.status = BrowserStatus.ERROR
                tab0.status = BrowserStatus.ERROR

                try:
                    db = get_db()
                    await db.add_log(
                        "ERROR",
                        f"Browser {self.browser_id} Tab 0 preheat error: {e}",
                        self.browser_id,
                    )
                except Exception:
                    pass
                return

            # 第一个标签页成功，继续创建其他标签页
            if self.max_tabs > 1:
                print(
                    f"[Browser {self.browser_id}] Creating {self.max_tabs - 1} more tabs..."
                )

                async def create_tab(tab_id: int, preferred_model: str) -> TabInstance:
                    """创建单个标签页"""
                    tab = TabInstance(
                        tab_id=tab_id,
                        browser_id=self.browser_id,
                        preferred_model=preferred_model,
                    )

                    new_page = await self.base_editor.context.new_page()

                    try:
                        await new_page.goto(
                            "https://gemini.google.com/app",
                            wait_until="load",
                            timeout=60000,
                        )
                        print(
                            f"[Browser {self.browser_id}] Tab {tab_id} navigated to Gemini"
                        )
                    except Exception as e:
                        print(
                            f"[Browser {self.browser_id}] Tab {tab_id} navigation warning: {e}"
                        )

                    new_editor = GeminiEditor(
                        account_id=0,
                        proxy=self.proxy,
                        enable_logging=False,
                        user_data_dir=self.user_data_dir,
                    )
                    new_editor.playwright = self.base_editor.playwright
                    new_editor.context = self.base_editor.context
                    new_editor.page = new_page
                    tab.editor = new_editor

                    print(
                        f"[Browser {self.browser_id}] Tab {tab_id} created (preferred: {preferred_model})"
                    )
                    return tab

                # 并行创建其他标签页
                create_tasks = []
                for i in range(1, self.max_tabs):
                    preferred_model = "Fast" if i < fast_count else "Pro"
                    create_tasks.append(create_tab(i, preferred_model))

                other_tabs = await asyncio.gather(*create_tasks)
                self.tabs.extend(other_tabs)

                # 并行预热其他标签页
                print(
                    f"[Browser {self.browser_id}] Preheating {len(other_tabs)} more tabs..."
                )
                preheat_start = time.time()

                async def preheat_tab(tab: TabInstance):
                    """预热单个标签页"""
                    tab.status = BrowserStatus.PREHEATING
                    try:
                        tab_start = time.time()
                        success = await tab.editor.prepare_environment(
                            model=tab.preferred_model,
                            temporary_chat=False,
                        )
                        elapsed = time.time() - tab_start
                        if success:
                            tab.status = BrowserStatus.IDLE
                            print(
                                f"[Browser {self.browser_id}] Tab {tab.tab_id} ({tab.preferred_model}) preheated ({elapsed:.3f}s)"
                            )
                        else:
                            print(
                                f"[Browser {self.browser_id}] Tab {tab.tab_id} ({tab.preferred_model}) preheat failed ({elapsed:.3f}s), reinitializing..."
                            )
                            await tab.reinitialize()
                    except Exception as e:
                        print(
                            f"[Browser {self.browser_id}] Tab {tab.tab_id} ({tab.preferred_model}) preheat error: {e}, reinitializing..."
                        )
                        await tab.reinitialize()

                await asyncio.gather(
                    *[preheat_tab(tab) for tab in other_tabs], return_exceptions=True
                )

                preheat_elapsed = time.time() - preheat_start
                print(
                    f"[Browser {self.browser_id}] Other tabs preheated in {preheat_elapsed:.3f}s"
                )

            self.status = BrowserStatus.IDLE
            self.last_active_at = datetime.now()
            print(
                f"[Browser {self.browser_id}] Started successfully with {len(self.tabs)} tabs"
            )

            try:
                db = get_db()
                await db.add_log(
                    "INFO",
                    f"Browser {self.browser_id} started with {len(self.tabs)} tabs",
                    self.browser_id,
                )
            except Exception:
                pass

        except Exception as e:
            self.status = BrowserStatus.ERROR
            print(f"[Browser {self.browser_id}] Failed to start: {e}")

            try:
                db = get_db()
                await db.add_log(
                    "ERROR",
                    f"Browser {self.browser_id} failed to start: {e}",
                    self.browser_id,
                )
            except Exception:
                pass

            raise

    async def stop(self):
        """停止浏览器和所有标签页"""
        print(f"[Browser {self.browser_id}] Stopping...")
        self.status = BrowserStatus.STOPPING

        try:
            # 关闭所有标签页（除了第一个）
            for tab in self.tabs:
                try:
                    if tab.editor and tab.tab_id > 0:  # 不关闭主编辑器的 page
                        await tab.editor.page.close()
                except Exception as e:
                    print(
                        f"[Browser {self.browser_id}] Error closing tab {tab.tab_id}: {e}"
                    )

            # 关闭主浏览器（这会关闭 context 和所有剩余的 pages）
            if self.base_editor:
                await self.base_editor.close()

            self.tabs = []
            self.status = BrowserStatus.STOPPED
            print(f"[Browser {self.browser_id}] Stopped")

            # 记录日志
            try:
                db = get_db()
                await db.add_log(
                    "INFO", f"Browser {self.browser_id} stopped", self.browser_id
                )
            except Exception:
                pass

        except Exception as e:
            print(f"[Browser {self.browser_id}] Error while stopping: {e}")
            self.status = BrowserStatus.ERROR

    def get_available_tab(
        self, preferred_model: Optional[str] = None
    ) -> Optional[TabInstance]:
        """
        获取空闲的标签页（智能选择策略）

        Args:
            preferred_model: 首选模型（"Pro" 或 "Fast"）

        策略：
        1. 优先选择与任务模型匹配的标签页
        2. Pro 任务优先使用 index 大的标签（降序）
        3. Fast 任务优先使用 index 小的标签（升序）
        4. 如果没有匹配的，降级选择其他空闲标签
        """
        idle_tabs = [tab for tab in self.tabs if tab.status == BrowserStatus.IDLE]

        if not idle_tabs:
            return None

        # 如果没有指定首选模型，返回第一个空闲标签
        if not preferred_model:
            return idle_tabs[0]

        # 按首选模型筛选
        matching_tabs = [
            tab for tab in idle_tabs if tab.preferred_model == preferred_model
        ]

        if matching_tabs:
            # 有匹配的标签页
            if preferred_model == "Pro":
                # Pro 任务：选择 index 最大的（降序排序后取第一个）
                return sorted(matching_tabs, key=lambda t: t.tab_id, reverse=True)[0]
            else:  # Fast
                # Fast 任务：选择 index 最小的（升序排序后取第一个）
                return sorted(matching_tabs, key=lambda t: t.tab_id)[0]
        else:
            # 没有匹配的标签页，降级选择任意空闲标签
            # 按相反优先级选择（避免饥饿）
            if preferred_model == "Pro":
                # Pro 任务降级：选择最大 index 的 Fast 标签
                return sorted(idle_tabs, key=lambda t: t.tab_id, reverse=True)[0]
            else:  # Fast
                # Fast 任务降级：选择最小 index 的 Pro 标签
                return sorted(idle_tabs, key=lambda t: t.tab_id)[0]

    def get_busy_tabs_count(self) -> int:
        """获取忙碌的标签页数量"""
        return sum(1 for tab in self.tabs if tab.status == BrowserStatus.BUSY)

    async def execute_task(
        self, task_id: str, input_image: str, prompt: str, model: str = "Fast"
    ) -> Optional[List[str]]:
        """执行图片编辑任务（使用空闲的标签页）"""
        # 检查速率限制
        allowed, info = self.check_rate_limit()
        if not allowed:
            raise RateLimitExceeded(
                browser_id=self.browser_id,
                limit=info["limit"],
                window_seconds=info["window_seconds"],
                reset_at=info["reset"],
            )

        # 获取空闲标签页（传入模型偏好）
        tab = self.get_available_tab(preferred_model=model)
        if not tab:
            raise NoAvailableTabs(browser_id=self.browser_id, total_tabs=len(self.tabs))

        print(
            f"[Browser {self.browser_id}] Task {task_id} assigned to Tab {tab.tab_id} (preferred: {tab.preferred_model}, requested: {model})"
        )

        # 记录请求
        self.record_request()

        # 在标签页中执行任务
        try:
            result = await tab.execute_task(task_id, input_image, prompt, model)
            if result:
                self.total_tasks += 1
            else:
                self.failed_tasks += 1
            self.last_active_at = datetime.now()
            return result
        except Exception:
            self.failed_tasks += 1
            raise

    async def execute_fast_task(
        self,
        task_id: str,
        input_images: List[str],
        prompt: str,
        model: str = "Fast",
        output_dir: str = "data/outputs",
        remove_watermark: bool = True,
        download_mode: str = "both",
    ) -> Optional[Dict[str, Any]]:
        """执行快速预览任务（使用空闲的标签页）

        Args:
            task_id: 任务ID
            input_images: 输入图片路径列表（支持多图）
            prompt: 编辑指令
            model: 模型类型 (Fast/Pro)
            output_dir: 输出目录
            remove_watermark: 是否去水印（默认 True）
            download_mode: 下载模式 (preview/hd/both)
        """
        # 检查速率限制
        allowed, info = self.check_rate_limit()
        if not allowed:
            raise RateLimitExceeded(
                browser_id=self.browser_id,
                limit=info["limit"],
                window_seconds=info["window_seconds"],
                reset_at=info["reset"],
            )

        # 获取空闲标签页（传入模型偏好）
        tab = self.get_available_tab(preferred_model=model)
        if not tab:
            raise NoAvailableTabs(browser_id=self.browser_id, total_tabs=len(self.tabs))

        print(
            f"[Browser {self.browser_id}] Fast task {task_id} assigned to Tab {tab.tab_id} (preferred: {tab.preferred_model}, requested: {model})"
        )

        # 记录请求
        self.record_request()

        # 在标签页中执行快速任务
        try:
            result = await tab.execute_fast_task(
                task_id=task_id,
                input_images=input_images,
                prompt=prompt,
                model=model,
                output_dir=output_dir,
                remove_watermark=remove_watermark,
                download_mode=download_mode,
            )
            if result:
                self.total_tasks += 1
            else:
                self.failed_tasks += 1
            self.last_active_at = datetime.now()
            return result
        except Exception:
            self.failed_tasks += 1
            raise

    async def check_login(self) -> Dict:
        """检查登录状态"""
        if not self.base_editor:
            return {
                "logged_in": False,
                "error": "Browser not ready",
            }

        try:
            # 尝试访问 Gemini 页面检查登录状态
            page = self.base_editor.page
            await page.goto(
                "https://gemini.google.com/", wait_until="networkidle", timeout=30000
            )

            # 检查是否有登录按钮或用户头像
            # 登录状态下通常会显示用户头像或账号信息
            logged_in = False

            # 检查是否有 "Sign in" 按钮
            sign_in_button = await page.query_selector('text="Sign in"')
            if not sign_in_button:
                # 检查是否有用户头像（已登录状态）
                avatar = await page.query_selector(
                    '[aria-label*="Account"], [data-ogsr-up], img[alt*="Account"]'
                )
                if avatar:
                    logged_in = True

            return {
                "logged_in": logged_in,
                "browser_id": self.browser_id,
                "account_name": self.account_name,
            }

        except Exception as e:
            return {
                "logged_in": False,
                "error": str(e),
            }

    def to_dict(self) -> Dict:
        """转换为字典"""
        _, rate_info = self.check_rate_limit()

        # 统计标签页状态
        idle_tabs = sum(1 for tab in self.tabs if tab.status == BrowserStatus.IDLE)
        busy_tabs = sum(1 for tab in self.tabs if tab.status == BrowserStatus.BUSY)

        # 统计首选模型分布
        fast_tabs = sum(1 for tab in self.tabs if tab.preferred_model == "Fast")
        pro_tabs = sum(1 for tab in self.tabs if tab.preferred_model == "Pro")

        # 详细标签页信息
        tabs_info = [
            {
                "tab_id": tab.tab_id,
                "preferred_model": tab.preferred_model,
                "status": tab.status.value,
                "total_tasks": tab.total_tasks,
                "failed_tasks": tab.failed_tasks,
            }
            for tab in self.tabs
        ]

        return {
            "browser_id": self.browser_id,
            "account_name": self.account_name,
            "proxy": self.proxy,
            "headless": self.headless,
            "status": self.status.value,
            "user_data_dir": self.user_data_dir,
            "created_at": self.created_at.isoformat(),
            "last_active_at": (
                self.last_active_at.isoformat() if self.last_active_at else None
            ),
            "total_tasks": self.total_tasks,
            "failed_tasks": self.failed_tasks,
            "max_tabs": self.max_tabs,
            "total_tabs": len(self.tabs),
            "idle_tabs": idle_tabs,
            "busy_tabs": busy_tabs,
            "fast_tabs": fast_tabs,
            "pro_tabs": pro_tabs,
            "tabs": tabs_info,
            "rate_limit": {
                "limit": self.rate_limit,
                "window_seconds": self.rate_window,
                "remaining": rate_info["remaining"],
                "reset": rate_info["reset"],
            },
        }
