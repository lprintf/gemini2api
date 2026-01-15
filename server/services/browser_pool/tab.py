"""标签页实例"""

import asyncio
import base64
import hashlib
import json
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.browser import AVATAR_PATTERN
from core.editor import GeminiEditor
from core.watermark_remover import WatermarkRemover
from server.core.database import get_db

from .exceptions import BrowserStatus


class TabInstance:
    """标签页实例"""

    def __init__(self, tab_id: int, browser_id: str, preferred_model: str = "Fast"):
        self.tab_id = tab_id
        self.browser_id = browser_id
        self.editor: Optional[GeminiEditor] = None
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
            result = await self.editor.edit_image(
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
                        target_url
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
                await self.editor.prepare_environment(
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
