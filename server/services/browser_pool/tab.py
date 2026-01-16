"""标签页实例"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.editor import GeminiEditor
from server.core.database import get_db

from .exceptions import BrowserStatus


class TabInstance:
    """标签页实例"""

    def __init__(self, tab_id: int, browser_id: str, preferred_model: str = "Fast"):
        self.tab_id = tab_id
        self.browser_id = browser_id
        self.editor: Optional[GeminiEditor] = None
        self.status = BrowserStatus.STARTING  # 初始状态为 STARTING，预热完成后才变为 IDLE
        self.preferred_model = preferred_model  # 标签页的首选模型
        self.current_task_id: Optional[str] = None
        self.total_tasks = 0
        self.failed_tasks = 0
        self.consecutive_failures = 0  # 连续失败次数
        self.last_active_at: Optional[datetime] = None
        # 高清下载相关
        self.hd_metadata: Optional[Dict[str, Any]] = None  # 预览图元数据
        self.hd_download_task: Optional[asyncio.Task] = None  # 后台高清下载任务

    async def reinitialize(self) -> bool:
        """重新初始化标签页（刷新页面并预热环境）"""
        print(f"[Tab {self.browser_id}-{self.tab_id}] Reinitializing...")
        self.status = BrowserStatus.STARTING

        try:
            if self.editor:
                success = await self.editor.reinitialize(model=self.preferred_model)
                if success:
                    self.consecutive_failures = 0
                    self.status = BrowserStatus.IDLE
                    print(f"[Tab {self.browser_id}-{self.tab_id}] Reinitialized successfully")
                    return True
                else:
                    self.status = BrowserStatus.ERROR
                    return False
        except Exception as e:
            print(f"[Tab {self.browser_id}-{self.tab_id}] Reinitialize failed: {e}")
            self.status = BrowserStatus.ERROR
            return False

        return False

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
                self.consecutive_failures = 0  # 成功后重置连续失败计数
                result_paths = result
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Task {task_id} completed successfully"
                )
            else:
                self.failed_tasks += 1
                error_message = "No result returned"
                print(f"[Tab {self.browser_id}-{self.tab_id}] Task {task_id} failed")

            # 成功完成后清理
            await self._finalize_task(task_id, result_paths, error_message, start_time)
            return result

        except Exception as e:
            self.failed_tasks += 1
            self.consecutive_failures += 1
            error_message = str(e)
            print(f"[Tab {self.browser_id}-{self.tab_id}] Task {task_id} error: {e}")

            # 后台重新初始化标签页
            print(
                f"[Tab {self.browser_id}-{self.tab_id}] Starting background reinitialize..."
            )
            asyncio.create_task(self._reinit_after_error())
            raise

    async def _reinit_after_error(self):
        """错误后重新初始化（内部方法）"""
        self.current_task_id = None
        await self.reinitialize()

    async def _finalize_task(
        self, task_id: str, result_paths, error_message, start_time: float
    ):
        """完成任务后的清理工作"""
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
        input_images: List[str],
        prompt: str,
        model: str = "Fast",
        output_dir: str = "data/outputs",
        remove_watermark: bool = True,
        download_mode: str = "both",
    ) -> Optional[Dict[str, Any]]:
        """
        执行快速预览任务

        流程：
        1. 准备环境 → 上传图片 → 提交生成 → 等待生成
        2. 根据 download_mode 下载图片
        3. 返回图片信息给调用者
        4. 后台预热标签页

        输出目录结构：
        - 预览图：outputs/q/{date}/{hash}.webp
        - 高清图：outputs/hd/{date}/{hash}.webp
        - 元数据：outputs/meta/{date}/{hash}.json

        Args:
            task_id: 任务ID
            input_images: 输入图片路径列表（支持单图和多图）
            prompt: 编辑指令
            model: 模型类型 (Fast/Pro)
            output_dir: 输出目录
            remove_watermark: 是否去水印（默认 True）
            download_mode: 下载模式
                - "preview": 只下载预览图（最快）
                - "hd": 只下载HD图（同步等待）
                - "both": 预览图 + 后台HD（默认）

        Returns:
            Dict with images info:
            {
                "task_id": "task-xxx",
                "images": [
                    {"hash": "abc123", "id": "20260107/abc123", ...}
                ],
            }
        """
        if self.status != BrowserStatus.IDLE:
            raise RuntimeError(
                f"Tab {self.browser_id}-{self.tab_id} is not idle (status: {self.status})"
            )

        print(f"[Tab {self.browser_id}-{self.tab_id}] Executing fast task {task_id}")
        print(f"  Input images: {len(input_images)} file(s)")
        for i, img in enumerate(input_images[:3]):  # 只打印前3个
            print(f"    [{i}] {img}")
        if len(input_images) > 3:
            print(f"    ... and {len(input_images) - 3} more")
        print(f"  Prompt: {prompt[:50]}...")
        print(f"  Model: {model}")

        self.status = BrowserStatus.BUSY
        self.current_task_id = task_id
        self.last_active_at = datetime.now()

        total_start = time.time()
        timings = {}
        base_output_dir = Path(output_dir)

        try:
            # 1. 准备页面环境（统一单图和多图逻辑）
            stage_start = time.time()

            if not await self.editor.prepare_environment(model=model, temporary_chat=False):
                raise RuntimeError("Failed to prepare environment")

            # 批量上传图片（单图也走这个逻辑）
            if not await self.editor.upload_images_by_paste(input_images):
                raise RuntimeError("Failed to upload images")

            # 输入提示词
            if not await self.editor.input_prompt(prompt):
                raise RuntimeError("Failed to input prompt")

            timings["prepare"] = time.time() - stage_start
            print(f"  ⏱ [准备阶段] {timings['prepare']:.3f}s")

            # 2. 提交生成请求
            stage_start = time.time()
            if not await self.editor.submit():
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

            # 4. 根据 download_mode 下载图片
            stage_start = time.time()
            date_str = datetime.now().strftime("%Y%m%d")
            images_info = []

            if download_mode == "hd":
                # 只下载 HD 图（同步等待）
                print(f"[Tab {self.browser_id}-{self.tab_id}] HD only mode")
                hd_dir = base_output_dir / "hd" / date_str
                hd_dir.mkdir(parents=True, exist_ok=True)

                # 获取所有生成图片的 URL
                image_urls = await self.editor._get_generated_image_urls()
                if not image_urls:
                    raise RuntimeError("No generated images found")

                for i, url in enumerate(image_urls):
                    temp_path = hd_dir / f"temp_{i}.webp"
                    success, hd_info = await self.editor.download_hd_by_url(
                        url=url,
                        save_path=str(temp_path),
                        remove_watermark=remove_watermark,
                    )
                    if success and hd_info:
                        file_hash = hd_info["hash"]
                        final_path = hd_dir / f"{file_hash}.webp"
                        if temp_path.exists():
                            temp_path.rename(final_path)
                        images_info.append({
                            "index": i,
                            "hash": file_hash,
                            "id": f"{date_str}/{file_hash}",
                            "date": date_str,
                            "format": "webp",
                            "path": str(final_path),
                            "size": hd_info["size"],
                            "dimensions": hd_info["dimensions"],
                            "url": url,
                            "is_hd": True,
                        })
                        print(
                            f"[Tab {self.browser_id}-{self.tab_id}] HD {i} saved: {file_hash[:16]}... ({hd_info['size']/1024:.1f}KB, {hd_info['dimensions']})"
                        )

                timings["download"] = time.time() - stage_start
                print(f"  ⏱ [HD下载] {timings['download']:.3f}s ({len(images_info)} 张)")
                hd_status = "completed"

            else:
                # preview 或 both 模式：先下载预览图
                preview_dir = base_output_dir / "q"
                images_info = await self.editor.download_all_previews(
                    output_dir=preview_dir,
                    remove_watermark=remove_watermark,
                    quality=80,
                )

                if not images_info:
                    raise RuntimeError("Failed to download any preview images")

                timings["download"] = time.time() - stage_start
                print(f"  ⏱ [预览下载] {timings['download']:.3f}s ({len(images_info)} 张)")

                for img_info in images_info:
                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] Preview {img_info['index']} saved: {img_info['hash'][:16]}... ({img_info['size']/1024:.1f}KB)"
                    )

                hd_status = "skipped" if download_mode == "preview" else "pending"

            if not images_info:
                raise RuntimeError("Failed to download any images")

            # 5. 为每张图保存独立的元数据到 outputs/meta/{date}/{hash}.json
            date_str = images_info[0]["date"] if images_info else date_str
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
                    "hd_status": hd_status,
                }
                meta_path = meta_dir / f"{img_info['hash']}.json"
                with open(meta_path, "w") as f:
                    json.dump(meta, f, indent=2)

            duration = time.time() - total_start
            print(
                f"\n[Tab {self.browser_id}-{self.tab_id}] Fast task {task_id} completed (mode: {download_mode})"
            )
            print(f"  ⏱ 总耗时: {duration:.3f}s")
            print(f"    准备: {timings.get('prepare', 0):.3f}s")
            print(f"    提交: {timings.get('submit', 0):.3f}s")
            print(f"    生成: {timings.get('generation', 0):.3f}s")
            print(f"    下载: {timings.get('download', 0):.3f}s")

            self.total_tasks += 1

            # 6. 根据 download_mode 决定后续操作
            if download_mode == "both":
                # 启动后台高清下载任务
                self.status = BrowserStatus.DOWNLOADING_HD
                self.hd_metadata = {"images": images_info, "date": date_str, "remove_watermark": remove_watermark}
                self._start_background_hd_download(base_output_dir, model)
            else:
                # preview 或 hd 模式：后台预热标签页
                print(f"[Tab {self.browser_id}-{self.tab_id}] Preheating...")
                self.status = BrowserStatus.PREHEATING
                self.current_task_id = None
                self.last_active_at = datetime.now()
                asyncio.create_task(self._preheat_after_skip(model))

            return {
                "task_id": task_id,
                "images": images_info,
            }

        except Exception as e:
            self.failed_tasks += 1
            self.consecutive_failures += 1

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

            self.current_task_id = None
            self.hd_metadata = None
            print(
                f"[Tab {self.browser_id}-{self.tab_id}] Fast task {task_id} error: {e}"
            )

            # 后台重新初始化标签页
            print(
                f"[Tab {self.browser_id}-{self.tab_id}] Starting background reinitialize (consecutive failures: {self.consecutive_failures})..."
            )
            asyncio.create_task(self.reinitialize())

            raise

    def _start_background_hd_download(self, base_output_dir: Path, model: str):
        """启动后台高清下载任务，保存到 outputs/hd/{date}/{hash}.webp"""

        async def download_all_hd():
            """下载所有图片的高清版本"""
            if not self.hd_metadata:
                return

            images = self.hd_metadata["images"]
            date_str = self.hd_metadata["date"]
            remove_watermark = self.hd_metadata.get("remove_watermark", True)

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

                    # 使用 editor 的方法下载 HD 图片（复用去水印和保存逻辑）
                    hd_path = hd_dir / f"{file_hash}.webp"
                    success, hd_info = await self.editor.download_hd_by_url(
                        url=target_url,
                        save_path=str(hd_path),
                        remove_watermark=remove_watermark,
                    )

                    if not success:
                        print(
                            f"[Tab {self.browser_id}-{self.tab_id}] HD download failed for {file_hash[:16]}"
                        )
                        self._update_meta_hd_status(
                            meta_dir / f"{file_hash}.json", "failed"
                        )
                        continue

                    # 更新元数据
                    self._update_meta_hd_status(
                        meta_dir / f"{file_hash}.json",
                        "completed",
                        hd_size=hd_info["size"],
                        hd_dimensions=hd_info["dimensions"],
                    )
                    success_count += 1

                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] HD saved: {file_hash[:16]}... ({hd_info['size']/1024:.1f}KB, {hd_info['dimensions']})"
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

            # 清理状态，准备预热
            self.current_task_id = None
            self.hd_metadata = None
            self.last_active_at = datetime.now()

            # 预热环境（准备下一个任务）
            self.status = BrowserStatus.PREHEATING
            try:
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Preheating for next task (model: {model})..."
                )
                success = await self.editor.prepare_environment(
                    model=model, temporary_chat=False
                )
                if success:
                    self.status = BrowserStatus.IDLE
                    print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat completed")
                else:
                    print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat failed, reinitializing...")
                    await self.reinitialize()
            except Exception as e:
                print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat failed: {e}")
                await self.reinitialize()

        self.hd_download_task = asyncio.create_task(download_all_hd())

    async def _preheat_after_skip(self, model: str):
        """跳过 HD 下载后的预热任务"""
        try:
            print(
                f"[Tab {self.browser_id}-{self.tab_id}] Preheating for next task (model: {model})..."
            )
            success = await self.editor.prepare_environment(model=model, temporary_chat=False)
            if success:
                print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat completed")
                self.status = BrowserStatus.IDLE
            else:
                print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat failed, reinitializing...")
                await self.reinitialize()
        except Exception as e:
            print(f"[Tab {self.browser_id}-{self.tab_id}] Preheat failed: {e}")
            await self.reinitialize()

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
