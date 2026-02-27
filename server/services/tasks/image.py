import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Any, Dict
from .base import BaseEngineTask, TaskResult
from . import actions
from ..objects.exceptions import BrowserStatus
from server.utils.logger import get_tab_logger, tab_log

class ImageGenerationTask(BaseEngineTask):
    """图片生成与编辑任务（逻辑编排层）"""
    
    async def run(self, tab: Any) -> TaskResult:
        page = tab.page
        # 挂载 per-tab logger，actions 层通过 tab_log(page, msg) 使用
        page._logger = get_tab_logger(tab.browser_id, tab.tab_id)
                # 1. 提取参数
        prompt = self.payload.get("prompt")
        input_images = self.payload.get("input_images", [])
        if not input_images and self.payload.get("input_image"):
            input_images = [self.payload.get("input_image")]
            
        model = self.payload.get("model", "Fast")
        remove_watermark = self.payload.get("remove_watermark", True)
        download_mode = self.payload.get("download_mode", "preview")

        durations = {}
        start_ts = time.time()

        try:
            # 2. 准备阶段
            tab.activity = "Preparing environment"
            t0 = time.time()
            success = await actions.prepare_environment(page, model=model)
            durations["prepare"] = round(time.time() - t0, 3)
            if not success:
                tab_log(page, "Environment preparation failed", "error")
                return TaskResult(success=False, error="Environment preparation failed")

            # 3. 输入与提交阶段
            tab.activity = "Uploading and submitting"
            t1 = time.time()
            success = await actions.submit_image_prompt(
                page, prompt, image_paths=input_images
            )
            durations["submit"] = round(time.time() - t1, 3)
            if not success:
                tab_log(page, "Failed to submit image prompt", "error")
                return TaskResult(success=False, error="Failed to submit image prompt")

            # 4. 生成阶段
            tab.activity = "Generating images..."
            t2 = time.time()
            success = await actions.wait_for_results(page, timeout_s=119)
            durations["generate"] = round(time.time() - t2, 3)
            if not success:
                tab_log(page, f"Timed out waiting for image results after {durations['generate']}s", "error")
                return TaskResult(success=False, error="Timed out waiting for image results")

            urls = await actions.get_generated_urls(page)
            if not urls:
                tab_log(page, "No images found in response", "error")
                return TaskResult(success=False, error="No images found in response")

            # 5. 下载处理阶段
            tab.activity = "Downloading & Processing"
            t3 = time.time()
            background_work = None

            if download_mode == "both":
                # both 模式：先同步下载预览图（客户端等这个），HD 下载作为后台任务
                images_info = await actions.download_generated_images(
                    page, remove_watermark=remove_watermark, download_mode="preview"
                )
                durations["download_preview"] = round(time.time() - t3, 3)

                # 构建 HD 下载协程，交给 coordinator 后台执行
                async def bg_hd_download():
                    t_hd = time.time()
                    tab.activity = "Background HD download"
                    hd_images = await actions.download_generated_images(
                        page, remove_watermark=remove_watermark, download_mode="hd"
                    )
                    tab_log(page, f"Background HD download: "
                          f"{len(hd_images)} images in {time.time() - t_hd:.1f}s")

                background_work = bg_hd_download()
            else:
                # preview 或 hd 模式：正常同步下载
                images_info = await actions.download_generated_images(
                    page, remove_watermark=remove_watermark, download_mode=download_mode
                )
                durations["download"] = round(time.time() - t3, 3)

            if not images_info:
                tab_log(page, "Failed to process any generated images", "error")
                return TaskResult(success=False, error="Failed to process any generated images")
            
            date_str = datetime.now().strftime("%Y%m%d")
            durations["total"] = round(time.time() - start_ts, 3)
            
            # 后端完成后打印耗时统计
            tab_log(page, f"Completed in {durations['total']}s: "
                  f"Prepare: {durations.get('prepare', 0)}s, "
                  f"Submit: {durations.get('submit', 0)}s, "
                  f"Generate: {durations.get('generate', 0)}s, "
                  f"Download: {durations.get('download', durations.get('download_preview', 0))}s")

            return TaskResult(
                success=True, 
                data={"images": images_info, "date": date_str},
                metadata={"model": model, "prompt": prompt, "download_mode": download_mode},
                background_work=background_work
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            tab_log(page, f"Task failed with exception: {str(e)}", "error")
            return TaskResult(success=False, error=str(e))
        finally:
            tab.activity = "Idle"
