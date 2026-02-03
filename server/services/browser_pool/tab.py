"""标签页实例"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import actions
from server.core.database import get_db

from .exceptions import BrowserStatus


class TabInstance:
    """标签页实例"""

    def __init__(self, tab_id: int, browser_id: str, preferred_model: str = "Fast"):
        self.tab_id = tab_id
        self.browser_id = browser_id
        self.page: Any = None  # Playwright Page 对象
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
            if self.page:
                success = await actions.reinitialize_page(
                    self.page, model=self.preferred_model
                )
                if success:
                    self.consecutive_failures = 0
                    self.status = BrowserStatus.IDLE
                    print(
                        f"[Tab {self.browser_id}-{self.tab_id}] Reinitialized successfully"
                    )
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
            result = await actions.run_edit_pipeline(
                page=self.page,
                input_image=input_image,
                prompt=prompt,
                output_dir="data/outputs/images",
                model=model,
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
        """执行快速预览任务"""
        if self.status != BrowserStatus.IDLE:
            raise RuntimeError(
                f"Tab {self.browser_id}-{self.tab_id} is not idle (status: {self.status})"
            )

        print(f"[Tab {self.browser_id}-{self.tab_id}] Executing fast task {task_id}")
        self.status = BrowserStatus.BUSY
        self.current_task_id = task_id
        self.last_active_at = datetime.now()

        total_start = time.time()
        base_output_dir = Path(output_dir)

        try:
            # 1. 准备页面环境
            if not await actions.prepare_environment(self.page, model=model):
                raise RuntimeError("Failed to prepare environment")

            # 批量上传图片
            if not await actions.upload_images_by_paste(self.page, input_images):
                raise RuntimeError("Failed to upload images")

            # 输入提示词
            if not await actions.input_prompt(self.page, prompt):
                raise RuntimeError("Failed to input prompt")

            # 2. 提交生成请求
            if not await actions.submit(self.page):
                raise RuntimeError("Failed to submit generation")

            # 3. 等待生成完成
            generation_success = await actions.wait_for_generation(
                self.page, timeout=120
            )
            if not generation_success:
                print(
                    f"[Tab {self.browser_id}-{self.tab_id}] Generation timeout, waiting extra 10s..."
                )
                await asyncio.sleep(10)

            # 4. 根据 download_mode 下载图片
            date_str = datetime.now().strftime("%Y%m%d")
            images_info = []

            if download_mode == "hd":
                # 只下载 HD 图（同步等待）
                hd_dir = base_output_dir / "hd" / date_str
                hd_dir.mkdir(parents=True, exist_ok=True)

                image_urls = await actions.get_generated_image_urls(self.page)
                if not image_urls:
                    raise RuntimeError("No generated images found")

                for i, url in enumerate(image_urls):
                    temp_path = hd_dir / f"temp_{i}.webp"
                    success, hd_info = await actions.download_hd_by_url(
                        page=self.page,
                        url=url,
                        save_path=str(temp_path),
                        remove_watermark=remove_watermark,
                    )
                    if success and hd_info:
                        file_hash = hd_info["hash"]
                        final_path = hd_dir / f"{file_hash}.webp"
                        if temp_path.exists():
                            temp_path.rename(final_path)
                        images_info.append(
                            {
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
                            }
                        )
                hd_status = "completed"

            else:
                # preview 或 both 模式
                image_urls = await actions.get_generated_image_urls(self.page)
                if not image_urls:
                    raise RuntimeError("No generated images found")

                preview_dir = base_output_dir / "q" / date_str
                preview_dir.mkdir(parents=True, exist_ok=True)

                for i, url in enumerate(image_urls):
                    temp_path = preview_dir / f"temp_{i}.webp"
                    success, file_hash = await actions.download_image_by_index(
                        page=self.page,
                        index=i,
                        save_path=str(temp_path),
                        remove_watermark=remove_watermark,
                        skip_hd=True,
                    )
                    if success and file_hash:
                        final_path = preview_dir / f"{file_hash}.webp"
                        if temp_path.exists():
                            temp_path.rename(final_path)
                        images_info.append(
                            {
                                "index": i,
                                "hash": file_hash,
                                "id": f"{date_str}/{file_hash}",
                                "date": date_str,
                                "format": "webp",
                                "path": str(final_path),
                                "size": final_path.stat().st_size
                                if final_path.exists()
                                else 0,
                                "url": url,
                            }
                        )

                hd_status = "skipped" if download_mode == "preview" else "pending"

            if not images_info:
                raise RuntimeError("Failed to download any images")

            # 5. 保存元数据
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

            # 6. 后续处理
            if download_mode == "both":
                self.status = BrowserStatus.DOWNLOADING_HD
                self.hd_metadata = {
                    "images": images_info,
                    "date": date_str,
                    "remove_watermark": remove_watermark,
                }
                self._start_background_hd_download(base_output_dir, model)
            else:
                self.status = BrowserStatus.PREHEATING
                self.current_task_id = None
                asyncio.create_task(self._preheat_after_skip(model))

            return {
                "task_id": task_id,
                "images": images_info,
            }

        except Exception as e:
            self.failed_tasks += 1
            self.consecutive_failures += 1
            # 截图调试
            try:
                error_dir = base_output_dir / "errors"
                error_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                await self.page.screenshot(
                    path=str(
                        error_dir
                        / f"error_{self.browser_id}_{self.tab_id}_{timestamp}.png"
                    )
                )
            except:
                pass

            self.current_task_id = None
            asyncio.create_task(self.reinitialize())
            raise

    def _start_background_hd_download(self, base_output_dir: Path, model: str):
        """启动后台高清下载任务"""

        async def download_all_hd():
            if not self.hd_metadata:
                return

            images = self.hd_metadata["images"]
            date_str = self.hd_metadata["date"]
            remove_watermark = self.hd_metadata.get("remove_watermark", True)
            hd_dir = base_output_dir / "hd" / date_str
            hd_dir.mkdir(parents=True, exist_ok=True)
            meta_dir = base_output_dir / "meta" / date_str

            for img_info in images:
                try:
                    success, hd_info = await actions.download_hd_by_url(
                        page=self.page,
                        url=img_info["url"],
                        save_path=str(hd_dir / f"{img_info['hash']}.webp"),
                        remove_watermark=remove_watermark,
                    )
                    status = "completed" if success else "failed"
                    self._update_meta_hd_status(
                        meta_dir / f"{img_info['hash']}.json",
                        status,
                        hd_size=hd_info["size"] if success else 0,
                        hd_dimensions=hd_info["dimensions"] if success else "",
                    )
                except:
                    self._update_meta_hd_status(
                        meta_dir / f"{img_info['hash']}.json", "failed"
                    )

            self.status = BrowserStatus.PREHEATING
            await actions.prepare_environment(self.page, model=model)
            self.status = BrowserStatus.IDLE

        self.hd_download_task = asyncio.create_task(download_all_hd())

    async def _preheat_after_skip(self, model: str):
        """跳过 HD 下载后的预热任务"""
        await actions.prepare_environment(self.page, model=model)
        self.status = BrowserStatus.IDLE

    def _update_meta_hd_status(self, meta_path: Path, status: str, **kwargs):
        """更新元数据中的 HD 状态"""
        try:
            if not meta_path.exists():
                return
            with open(meta_path, "r") as f:
                meta = json.load(f)
            meta["hd_status"] = status
            meta.update(kwargs)
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except:
            pass
