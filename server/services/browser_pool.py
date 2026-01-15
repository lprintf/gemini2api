"""
浏览器池管理器

负责管理多个浏览器实例，每个实例：
- 使用独立的 user_data_dir
- 可以配置独立的代理
- 可以登录不同的 Google 账号
- 支持负载均衡
- 支持浏览器级别的速率限制
- 支持 SQLite 数据库持久化
"""

import asyncio
import base64
import hashlib
import json
import random
import time
from collections import deque
from datetime import datetime
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.browser import AVATAR_PATTERN
from core.enhanced_editor import EnhancedGeminiImageEditor
from core.watermark_remover import WatermarkRemover
from server.core.database import get_db
from server.core.models import BrowserConfig, TaskRecord


class RateLimitExceeded(Exception):
    """速率限制异常"""

    def __init__(self, browser_id: str, limit: int, window_seconds: int, reset_at: int):
        self.browser_id = browser_id
        self.limit = limit
        self.window_seconds = window_seconds
        self.reset_at = reset_at
        self.retry_after = max(0, reset_at - int(time.time()))
        super().__init__(
            f"Browser {browser_id} rate limit exceeded. "
            f"Limit: {limit}/{window_seconds}s, Reset at: {reset_at}"
        )


class NoAvailableTabs(Exception):
    """没有可用标签页异常"""

    def __init__(self, browser_id: str, total_tabs: int):
        self.browser_id = browser_id
        self.total_tabs = total_tabs
        super().__init__(
            f"Browser {browser_id} has no available tabs (all {total_tabs} tabs are busy)"
        )


class BrowserStatus(str, Enum):
    """浏览器状态"""

    IDLE = "idle"  # 空闲，可接受任务
    BUSY = "busy"  # 忙碌，正在处理任务
    DOWNLOADING_HD = "downloading_hd"  # 后台下载高清图中
    STARTING = "starting"  # 启动中
    STOPPING = "stopping"  # 停止中
    ERROR = "error"  # 错误状态
    STOPPED = "stopped"  # 已停止


class TabInstance:
    """标签页实例"""

    def __init__(self, tab_id: int, browser_id: str, preferred_model: str = "Fast"):
        self.tab_id = tab_id
        self.browser_id = browser_id
        self.editor: Optional[EnhancedGeminiImageEditor] = None
        self.status = BrowserStatus.IDLE
        self.preferred_model = preferred_model  # 标签页的首选模型
        self.current_task_id: Optional[str] = None
        self.total_tasks = 0
        self.failed_tasks = 0
        self.last_active_at: Optional[datetime] = None
        # 高清下载相关
        self.hd_metadata: Optional[Dict[str, Any]] = None  # 预览图元数据
        self.hd_download_task: Optional[asyncio.Task] = None  # 后台高清下载任务

    async def execute_task(
        self, task_id: str, input_image: str, prompt: str, model: str = "Fast"
    ) -> Optional[List[str]]:
        """执行图片编辑任务"""
        if self.status != BrowserStatus.IDLE:
            raise RuntimeError(
                f"Tab {self.browser_id}-{self.tab_id} is not idle (status: {self.status})"
            )

        print(f"[Tab {self.browser_id}-{self.tab_id}] Executing task {task_id}")
        self.status = BrowserStatus.BUSY
        self.current_task_id = task_id
        self.last_active_at = datetime.now()

        start_time = time.time()
        result_paths = None
        error_message = None

        try:
            result = await self.editor.edit_image_enhanced(
                input_image=input_image,
                prompt=prompt,
                output_dir="data/outputs/images",
                model=model,
                temporary_chat=False,
                output_format="webp",
                webp_lossless=True,
                save_log=True,
            )

            if result:
                self.total_tasks += 1
                result_paths = result
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Task {task_id} completed successfully"
                )
            else:
                self.failed_tasks += 1
                error_message = "No result returned"
                print(f"[Tab {self.browser_id}-{self.tab_id}] Task {task_id} failed")

            return result

        except Exception as e:
            self.failed_tasks += 1
            error_message = str(e)
            print(f"[Tab {self.browser_id}-{self.tab_id}] Task {task_id} error: {e}")
            raise

        finally:
            self.status = BrowserStatus.IDLE
            self.current_task_id = None
            self.last_active_at = datetime.now()
            duration = time.time() - start_time

            # 更新任务记录到数据库
            try:
                db = get_db()
                await db.update_task(
                    task_id,
                    {
                        "browser_id": f"{self.browser_id}-tab{self.tab_id}",
                        "status": "completed" if result_paths else "failed",
                        "result_paths": result_paths,
                        "error_message": error_message,
                        "duration": duration,
                        "completed_at": datetime.now(),
                    },
                )
            except Exception as db_error:
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Failed to update task in DB: {db_error}"
                )

    async def execute_fast_task(
        self,
        task_id: str,
        input_image: str,
        prompt: str,
        model: str = "Fast",
        output_dir: str = "data/outputs",
    ) -> Optional[Dict[str, Any]]:
        """
        执行快速预览任务，预览图返回后立即启动后台高清下载

        流程：
        1. 准备环境 → 提交生成 → 等待生成
        2. 快速下载预览图（page.request.get）
        3. 立即返回预览图信息给调用者
        4. 后台启动高清下载任务
        5. 高清下载完成后自动释放标签页

        输出目录结构：
        - 预览图：outputs/q/{date}/{hash}.{fmt}
        - 高清图：outputs/hd/{date}/{hash}.webp
        - 元数据：outputs/meta/{date}/{hash}.json

        Returns:
            Dict with preview images info:
            {
                "task_id": "task-xxx",
                "images": [
                    {"hash": "abc123", "id": "20260107/abc123", "url": "..."}
                ],
            }
        """
        if self.status != BrowserStatus.IDLE:
            raise RuntimeError(
                f"Tab {self.browser_id}-{self.tab_id} is not idle (status: {self.status})"
            )

        print(f"[Tab {self.browser_id}-{self.tab_id}] Executing fast task {task_id}")
        print(f"  Input: {input_image}")
        print(f"  Prompt: {prompt[:50]}...")
        print(f"  Model: {model}")

        self.status = BrowserStatus.BUSY
        self.current_task_id = task_id
        self.last_active_at = datetime.now()

        total_start = time.time()
        timings = {}
        base_output_dir = Path(output_dir)

        try:
            # 1. 准备页面环境并执行生成
            stage_start = time.time()
            success = await self.editor.prepare_for_generation(
                input_image=input_image,
                prompt=prompt,
                model=model,
                temporary_chat=False,
            )

            if not success:
                raise RuntimeError("Failed to prepare for generation")
            timings["prepare"] = time.time() - stage_start
            print(f"  ⏱ [准备阶段] {timings['prepare']:.3f}s")

            # 2. 提交生成请求
            stage_start = time.time()
            if not await self.editor.submit_generation():
                raise RuntimeError("Failed to submit generation")
            timings["submit"] = time.time() - stage_start
            print(f"  ⏱ [提交请求] {timings['submit']:.3f}s")

            # 3. 等待生成完成
            stage_start = time.time()
            generation_timeout = 120  # 2分钟
            generation_success = await self.editor.wait_for_generation(
                timeout=generation_timeout,
            )
            if not generation_success:
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Generation timeout ({generation_timeout}s), waiting extra 10s..."
                )
                await asyncio.sleep(10)
            timings["generation"] = time.time() - stage_start
            print(f"  ⏱ [生成等待] {timings['generation']:.3f}s")

            # 4. 快速下载预览图（使用 page.request.get）
            stage_start = time.time()
            page = self.editor.page
            containers = await page.query_selector_all("model-response")
            if not containers:
                raise RuntimeError("No response containers found")

            last_container = containers[-1]
            images = await last_container.query_selector_all("img")

            # 过滤出生成的图片
            image_urls = []
            for img in images:
                src = await img.get_attribute("src")
                if src and "googleusercontent" in src and AVATAR_PATTERN not in src:
                    image_urls.append(src)

            if not image_urls:
                raise RuntimeError("No generated images found")

            # 5. 下载预览图并计算 hash，保存到 outputs/q/{date}/{hash}.{fmt}
            date_str = datetime.now().strftime("%Y%m%d")
            preview_dir = base_output_dir / "q" / date_str
            preview_dir.mkdir(parents=True, exist_ok=True)

            images_info = []
            download_start = time.time()
            for i, url in enumerate(image_urls):
                response = await page.request.get(url)
                if not response.ok:
                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] Failed to download preview {i}: HTTP {response.status}"
                    )
                    continue

                image_bytes = await response.body()

                # 计算 hash
                sha256_hash = hashlib.sha256(image_bytes).digest()
                file_hash = base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")

                # 检测格式并保存到 q/{date}/{hash}.{fmt}
                fmt = self._detect_image_format(image_bytes)
                preview_path = preview_dir / f"{file_hash}.{fmt}"
                with open(preview_path, "wb") as f:
                    f.write(image_bytes)

                # id 格式：{date}/{hash}，用于 API 返回和 HD 请求
                image_id = f"{date_str}/{file_hash}"

                images_info.append(
                    {
                        "index": i,
                        "hash": file_hash,
                        "id": image_id,  # 统一标识符
                        "date": date_str,
                        "format": fmt,
                        "url": url,
                        "size": len(image_bytes),
                    }
                )

                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Preview {i} saved: {file_hash[:16]}... ({len(image_bytes)/1024:.1f}KB)"
                )

            timings["download"] = time.time() - download_start
            print(f"  ⏱ [预览下载] {timings['download']:.3f}s ({len(images_info)} 张)")

            if not images_info:
                raise RuntimeError("Failed to download any preview images")

            # 6. 为每张图保存独立的元数据到 outputs/meta/{date}/{hash}.json
            meta_dir = base_output_dir / "meta" / date_str
            meta_dir.mkdir(parents=True, exist_ok=True)

            for img_info in images_info:
                meta = {
                    "task_id": task_id,
                    "browser_id": self.browser_id,
                    "tab_id": self.tab_id,
                    "created_at": datetime.now().isoformat(),
                    "model": model,
                    "prompt": prompt,
                    "image": img_info,
                    "hd_status": "pending",  # pending → downloading → completed/failed
                }
                meta_path = meta_dir / f"{img_info['hash']}.json"
                with open(meta_path, "w") as f:
                    json.dump(meta, f, indent=2)

            duration = time.time() - total_start
            print(
                f"\n[Tab {self.browser_id}-{self.tab_id}] Fast task {task_id} preview completed"
            )
            print(f"  ⏱ 总耗时: {duration:.3f}s")
            print(f"    准备: {timings.get('prepare', 0):.3f}s")
            print(f"    提交: {timings.get('submit', 0):.3f}s")
            print(f"    生成: {timings.get('generation', 0):.3f}s")
            print(f"    下载: {timings.get('download', 0):.3f}s")

            self.total_tasks += 1

            # 7. 设置状态为 DOWNLOADING_HD，启动后台高清下载任务
            self.status = BrowserStatus.DOWNLOADING_HD
            self.hd_metadata = {"images": images_info, "date": date_str}
            self._start_background_hd_download(base_output_dir, model)

            return {
                "task_id": task_id,
                "images": images_info,
            }

        except Exception as e:
            self.failed_tasks += 1

            # 保存错误截图用于调试
            try:
                if self.editor and self.editor.page:
                    error_dir = base_output_dir / "errors"
                    error_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    screenshot_path = (
                        error_dir
                        / f"error_{self.browser_id}_{self.tab_id}_{timestamp}.png"
                    )
                    await self.editor.page.screenshot(
                        path=str(screenshot_path), full_page=True
                    )
                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] Error screenshot saved: {screenshot_path}"
                    )
            except Exception as screenshot_error:
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Failed to save error screenshot: {screenshot_error}"
                )

            self.status = BrowserStatus.IDLE
            self.current_task_id = None
            self.hd_metadata = None
            print(
                f"[Tab {self.browser_id}-{self.tab_id}] Fast task {task_id} error: {e}"
            )
            raise

    def _start_background_hd_download(self, base_output_dir: Path, model: str):
        """启动后台高清下载任务，保存到 outputs/hd/{date}/{hash}.webp"""

        async def download_all_hd():
            """下载所有图片的高清版本"""
            if not self.hd_metadata:
                return

            images = self.hd_metadata["images"]
            date_str = self.hd_metadata["date"]

            print(
                f"[Tab {self.browser_id}-{self.tab_id}] Starting background HD download for {len(images)} images..."
            )

            # HD 输出目录
            hd_dir = base_output_dir / "hd" / date_str
            hd_dir.mkdir(parents=True, exist_ok=True)

            # 元数据目录
            meta_dir = base_output_dir / "meta" / date_str

            hd_start = time.time()
            success_count = 0

            for img_info in images:
                try:
                    target_url = img_info["url"]
                    file_hash = img_info["hash"]

                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] Downloading HD for {file_hash[:16]}..."
                    )

                    # 使用 hover 下载按钮获取高清图
                    hd_bytes = await self.editor._download_via_hover_button(
                        target_url, "no_wait"
                    )

                    if not hd_bytes:
                        print(
                            f"[Tab {self.browser_id}-{self.tab_id}] HD download failed for {file_hash[:16]}"
                        )
                        self._update_meta_hd_status(
                            meta_dir / f"{file_hash}.json", "failed"
                        )
                        continue

                    # 去水印处理
                    try:
                        hd_bytes = WatermarkRemover.remove_watermark_from_bytes(
                            hd_bytes, verbose=False
                        )
                        print(
                            f"[Tab {self.browser_id}-{self.tab_id}] HD watermark removed for {file_hash[:16]}"
                        )
                    except Exception as wm_err:
                        print(
                            f"[Tab {self.browser_id}-{self.tab_id}] HD watermark removal failed for {file_hash[:16]}: {wm_err}"
                        )

                    # 转换为 WebP
                    from PIL import Image

                    pil_img = Image.open(BytesIO(hd_bytes))
                    width, height = pil_img.size

                    webp_buffer = BytesIO()
                    pil_img.save(webp_buffer, "WEBP", lossless=True)
                    webp_data = webp_buffer.getvalue()

                    # 保存高清图到 hd/{date}/{hash}.webp
                    hd_path = hd_dir / f"{file_hash}.webp"
                    with open(hd_path, "wb") as f:
                        f.write(webp_data)

                    # 更新元数据
                    self._update_meta_hd_status(
                        meta_dir / f"{file_hash}.json",
                        "completed",
                        hd_size=len(webp_data),
                        hd_dimensions=f"{width}x{height}",
                    )
                    success_count += 1

                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] HD saved: {file_hash[:16]}... ({len(webp_data)/1024:.1f}KB, {width}x{height})"
                    )

                except Exception as e:
                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] HD download error for {img_info.get('hash', '?')[:16]}: {e}"
                    )
                    self._update_meta_hd_status(
                        meta_dir / f"{img_info.get('hash', '')}.json", "failed"
                    )

            hd_duration = time.time() - hd_start
            print(
                f"[Tab {self.browser_id}-{self.tab_id}] Background HD download completed: {success_count}/{len(images)} in {hd_duration:.3f}s"
            )

            # 释放标签页，准备下一个任务
            self.status = BrowserStatus.IDLE
            self.current_task_id = None
            self.hd_metadata = None
            self.last_active_at = datetime.now()

            # 预热环境（准备下一个任务）
            try:
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Preheating for next task (model: {model})..."
                )
                await self.editor.prepare_page_environment(
                    model=model, temporary_chat=False
                )
                print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat completed")
            except Exception as e:
                print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat failed: {e}")

        self.hd_download_task = asyncio.create_task(download_all_hd())

    def _update_meta_hd_status(self, meta_path: Path, status: str, **kwargs):
        """更新元数据中的 HD 状态"""
        try:
            if not meta_path.exists():
                return
            with open(meta_path, "r") as f:
                meta = json.load(f)
            meta["hd_status"] = status
            meta["hd_completed_at"] = datetime.now().isoformat()
            for k, v in kwargs.items():
                meta[k] = v
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            print(f"[Tab {self.browser_id}-{self.tab_id}] Failed to update meta: {e}")

    def _detect_image_format(self, data: bytes) -> str:
        """根据文件头检测图片格式"""
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        elif data[:2] == b"\xff\xd8":
            return "jpg"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "webp"
        elif data[:6] in (b"GIF87a", b"GIF89a"):
            return "gif"
        else:
            return "bin"


class BrowserInstance:
    """浏览器实例（支持多标签页）"""

    def __init__(
        self,
        browser_id: str,
        account_name: str,
        proxy: Optional[str] = None,
        headless: bool = True,
        user_data_dir: Optional[str] = None,
        rate_limit: int = 10,  # 每分钟请求限制
        rate_window: int = 60,  # 时间窗口（秒）
        max_tabs: int = 6,  # 最大标签页数量
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
        self.base_editor: Optional[EnhancedGeminiImageEditor] = (
            None  # 主编辑器（用于创建标签页）
        )
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
        """启动浏览器并创建多个标签页"""
        print(f"[Browser {self.browser_id}] Starting with {self.max_tabs} tabs...")
        self.status = BrowserStatus.STARTING

        try:
            # 创建主编辑器（高并发场景禁用日志）
            self.base_editor = EnhancedGeminiImageEditor(
                account_id=0,
                headless=self.headless,
                proxy=self.proxy,
                enable_logging=False,  # 禁用事件监听，节省CPU
                user_data_dir=self.user_data_dir,
            )

            # 启动浏览器
            await self.base_editor.launch()
            print(f"[Browser {self.browser_id}] Base browser launched")

            # 创建多个标签页
            self.tabs = []

            # 计算标签页分配策略：一半 Pro，一半 Fast
            # Pro 标签：使用 index 大的（后半部分）
            # Fast 标签：使用 index 小的（前半部分）
            pro_count = self.max_tabs // 2
            fast_count = self.max_tabs - pro_count

            # Tab 0: 使用主编辑器（Fast 模型）
            tab0 = TabInstance(
                tab_id=0, browser_id=self.browser_id, preferred_model="Fast"
            )
            tab0.editor = self.base_editor
            self.tabs.append(tab0)
            print(f"[Browser {self.browser_id}] Tab 0 created (preferred: Fast)")

            # Tab 1+: 并行创建其他标签页
            if self.max_tabs > 1:

                async def create_tab(tab_id: int, preferred_model: str) -> TabInstance:
                    """并行创建单个标签页"""
                    tab = TabInstance(
                        tab_id=tab_id,
                        browser_id=self.browser_id,
                        preferred_model=preferred_model,
                    )

                    # 在同一个 context 中创建新的 page
                    new_page = await self.base_editor.context.new_page()

                    # 导航到 Gemini 页面（预热）
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

                    # 创建新的编辑器实例，复用 context 但使用新的 page
                    new_editor = EnhancedGeminiImageEditor(
                        account_id=0,
                        headless=self.headless,
                        proxy=self.proxy,
                        enable_logging=False,  # 只在主编辑器启用日志
                        user_data_dir=self.user_data_dir,
                    )
                    # 手动设置已启动的状态
                    new_editor.playwright = self.base_editor.playwright
                    new_editor.context = self.base_editor.context
                    new_editor.page = new_page
                    tab.editor = new_editor

                    print(
                        f"[Browser {self.browser_id}] Tab {tab_id} created (preferred: {preferred_model})"
                    )
                    return tab

                # 并行创建 Tab 1 到 Tab (max_tabs-1)
                # Tab 1 到 Tab (fast_count-1): Fast 模型
                # Tab fast_count 到 Tab (max_tabs-1): Pro 模型
                create_tasks = []
                for i in range(1, self.max_tabs):
                    preferred_model = "Fast" if i < fast_count else "Pro"
                    create_tasks.append(create_tab(i, preferred_model))

                other_tabs = await asyncio.gather(*create_tasks)
                self.tabs.extend(other_tabs)

            self.status = BrowserStatus.IDLE
            self.last_active_at = datetime.now()
            print(
                f"[Browser {self.browser_id}] Started successfully with {len(self.tabs)} tabs"
            )

            # 记录日志到数据库
            try:
                db = get_db()
                await db.add_log(
                    "INFO",
                    f"Browser {self.browser_id} started with {self.max_tabs} tabs",
                    self.browser_id,
                )
            except Exception:
                pass

            # 预热所有标签页（并行执行）
            print(
                f"[Browser {self.browser_id}] Preheating all {len(self.tabs)} tabs..."
            )
            preheat_start = time.time()

            async def preheat_tab(tab: TabInstance):
                """预热单个标签页（使用其首选模型）"""
                try:
                    tab_start = time.time()
                    success = await tab.editor.prepare_page_environment(
                        model=tab.preferred_model,  # 使用标签页的首选模型
                        temporary_chat=False,
                    )
                    elapsed = time.time() - tab_start
                    if success:
                        print(
                            f"[Browser {self.browser_id}] Tab {tab.tab_id} ({tab.preferred_model}) preheated successfully ({elapsed:.3f}s)"
                        )
                    else:
                        print(
                            f"[Browser {self.browser_id}] Tab {tab.tab_id} ({tab.preferred_model}) preheat failed ({elapsed:.3f}s)"
                        )
                except Exception as e:
                    print(
                        f"[Browser {self.browser_id}] Tab {tab.tab_id} ({tab.preferred_model}) preheat error: {e}"
                    )

            # 并行预热所有标签页
            await asyncio.gather(
                *[preheat_tab(tab) for tab in self.tabs], return_exceptions=True
            )

            preheat_elapsed = time.time() - preheat_start
            print(
                f"[Browser {self.browser_id}] All tabs preheated in {preheat_elapsed:.3f}s"
            )

        except Exception as e:
            self.status = BrowserStatus.ERROR
            print(f"[Browser {self.browser_id}] Failed to start: {e}")

            # 记录错误日志
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
        input_image: str,
        prompt: str,
        model: str = "Fast",
        output_dir: str = "data/outputs",
    ) -> Optional[Dict[str, Any]]:
        """执行快速预览任务（使用空闲的标签页）"""
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
                task_id, input_image, prompt, model, output_dir
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


class BrowserPool:
    """浏览器池管理器"""

    def __init__(
        self,
        min_browsers: int = 1,
        max_browsers: int = 20,
        browser_rate_limit: int = 9,  # 每个浏览器的速率限制
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
        """从数据库加载浏览器配置（并行启动）"""
        try:
            db = get_db()

            # 获取下一个可用 ID
            self._next_id = await db.get_next_browser_id()

            # 获取所有自动启动的浏览器配置
            configs = await db.get_auto_start_browsers()

            print(f"[BrowserPool] Loading {len(configs)} browsers from database...")

            if not configs:
                await db.add_log("INFO", "Browser pool loaded 0 browsers")
                return

            # 先创建所有 BrowserInstance 对象
            for config in configs:
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

            # 并行启动所有浏览器
            async def start_browser_safe(browser: BrowserInstance) -> tuple[str, bool, str]:
                """安全启动单个浏览器，返回 (browser_id, success, error_msg)"""
                try:
                    await browser.start()
                    return (browser.browser_id, True, "")
                except Exception as e:
                    return (browser.browser_id, False, str(e))

            print(f"[BrowserPool] Starting {len(self.browsers)} browsers in parallel...")
            start_time = time.time()

            results = await asyncio.gather(
                *[start_browser_safe(b) for b in self.browsers.values()]
            )

            # 处理启动结果
            success_count = 0
            for browser_id, success, error_msg in results:
                if success:
                    success_count += 1
                    print(f"[BrowserPool] Browser {browser_id} started successfully")
                else:
                    print(f"[BrowserPool] Failed to start browser {browser_id}: {error_msg}")
                    await db.add_log(
                        "ERROR",
                        f"Failed to load browser {browser_id}: {error_msg}",
                        browser_id,
                    )

            elapsed = time.time() - start_time
            print(
                f"[BrowserPool] Parallel startup completed: {success_count}/{len(configs)} "
                f"browsers in {elapsed:.2f}s"
            )

            await db.add_log(
                "INFO",
                f"Browser pool loaded {success_count}/{len(configs)} browsers in {elapsed:.2f}s"
            )

        except Exception as e:
            print(f"[BrowserPool] Failed to load from database: {e}")

    async def create_browser(
        self,
        browser_id: Optional[int] = None,  # 可选的浏览器 ID
        account_name: Optional[str] = None,  # 可选的账号名称
        proxy: Optional[str] = None,
        headless: bool = True,
        auto_start: bool = True,
        is_enabled: bool = True,
        max_tabs: int = 6,  # 最大标签页数量
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
                await browser.start()

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
            await browser.stop()
            del self.browsers[browser_id]

            # 从数据库删除
            try:
                db = get_db()
                await db.delete_browser(browser_id)
                await db.add_log("INFO", f"Browser {browser_id} removed", browser_id)
            except Exception as e:
                print(f"[BrowserPool] Failed to delete browser from database: {e}")

            print(f"[BrowserPool] Removed browser {browser_id}")

    async def start_browser(self, browser_id: str):
        """启动指定浏览器"""
        if browser_id not in self.browsers:
            raise KeyError(f"Browser {browser_id} not found")

        browser = self.browsers[browser_id]
        if browser.status != BrowserStatus.STOPPED:
            raise RuntimeError(
                f"Browser {browser_id} is not stopped (status: {browser.status})"
            )

        await browser.start()

    async def stop_browser(self, browser_id: str):
        """停止指定浏览器"""
        if browser_id not in self.browsers:
            raise KeyError(f"Browser {browser_id} not found")

        browser = self.browsers[browser_id]
        if browser.status == BrowserStatus.STOPPED:
            raise RuntimeError(f"Browser {browser_id} is already stopped")

        await browser.stop()

    async def get_available_browser(
        self, strategy: str = "least_loaded", preferred_model: Optional[str] = None
    ) -> Optional[BrowserInstance]:
        """
        获取可用的浏览器（负载均衡）

        Args:
            strategy: 负载均衡策略
            preferred_model: 首选模型（用于标签页选择）

        策略 (least_loaded):
        1. 首先按空闲标签页数量排序（多的优先）
        2. 空闲标签页相同时，按 rate limit 剩余量排序（多的优先）
        3. rate limit 也相同时，50% 概率随机分配
        4. 另外 50% 智能分配：
           - 优先分配给失败任务数少的浏览器
           - 失败任务数相同时，优先分配给处理任务少的标签页
        """
        # 只选择有空闲标签页的浏览器
        available_browsers = [
            browser
            for browser in self.browsers.values()
            if browser.status == BrowserStatus.IDLE
            and browser.get_available_tab(preferred_model) is not None
        ]

        if not available_browsers:
            return None

        if strategy == "least_loaded":
            # 按空闲标签页数量分组
            def get_idle_tabs_count(b: BrowserInstance) -> int:
                return len(b.tabs) - b.get_busy_tabs_count()

            # 找出空闲标签页最多的数量
            max_idle_tabs = max(get_idle_tabs_count(b) for b in available_browsers)

            # 筛选出空闲标签页数量最多的浏览器
            best_browsers = [
                b for b in available_browsers if get_idle_tabs_count(b) == max_idle_tabs
            ]

            if len(best_browsers) == 1:
                return best_browsers[0]

            # 空闲标签页相同时，先按 rate limit 剩余量筛选
            def get_rate_limit_remaining(b: BrowserInstance) -> int:
                _, info = b.check_rate_limit()
                return info["remaining"]

            max_remaining = max(get_rate_limit_remaining(b) for b in best_browsers)
            best_browsers = [
                b for b in best_browsers if get_rate_limit_remaining(b) == max_remaining
            ]

            if len(best_browsers) == 1:
                return best_browsers[0]

            # rate limit 也相同时，50% 概率随机分配
            if random.random() < 0.5:
                return random.choice(best_browsers)

            # 50% 智能分配：优先失败任务少的浏览器
            def get_tab_score(b: BrowserInstance) -> tuple:
                """
                返回 (失败任务数, 目标标签页的处理任务数)
                用于排序：数值越小越优先
                """
                tab = b.get_available_tab(preferred_model)
                tab_total_tasks = tab.total_tasks if tab else float("inf")
                return (b.failed_tasks, tab_total_tasks)

            # 按评分排序，选择最优的
            best_browsers.sort(key=get_tab_score)
            return best_browsers[0]

        elif strategy == "round_robin":
            # 简单轮询（选择第一个）
            return available_browsers[0]
        elif strategy == "random":
            # 随机选择
            return random.choice(available_browsers)
        else:
            return available_browsers[0]

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

        tasks = [browser.stop() for browser in self.browsers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self.browsers.clear()
        print("[BrowserPool] All browsers stopped")
