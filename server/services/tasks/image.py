import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Any, Dict
from .base import BaseEngineTask, TaskResult
from . import actions
from ..objects.exceptions import BrowserStatus

class ImageGenerationTask(BaseEngineTask):
    """图片生成与编辑任务（逻辑编排层）"""
    
    async def run(self, tab: Any) -> TaskResult:
        page = tab.page
        
        # 1. 提取参数
        prompt = self.payload.get("prompt")
        input_images = self.payload.get("input_images", [])
        if not input_images and self.payload.get("input_image"):
            input_images = [self.payload.get("input_image")]
            
        model = self.payload.get("model", "Fast")
        remove_watermark = self.payload.get("remove_watermark", True)
        download_mode = self.payload.get("download_mode", "preview")

        try:
            # 2. 准备阶段
            tab.activity = "Preparing environment"
            success = await actions.prepare_environment(page, model=model)
            if not success:
                return TaskResult(success=False, error="Environment preparation failed")

            # 3. 输入与提交阶段
            tab.activity = "Uploading and submitting"
            success = await actions.submit_image_prompt(
                page, prompt, image_paths=input_images
            )
            if not success:
                return TaskResult(success=False, error="Failed to submit image prompt")

            # 4. 生成阶段
            tab.activity = "Generating images..."
            success = await actions.wait_for_results(page, timeout_s=90)
            if not success:
                return TaskResult(success=False, error="Timed out waiting for image results")

            urls = await actions.get_generated_urls(page)
            if not urls:
                return TaskResult(success=False, error="No images found in response")

            # 5. 下载处理阶段
            tab.activity = "Downloading & Processing"
            images_info = []
            output_base = Path("data/outputs")
            date_str = datetime.now().strftime("%Y%m%d")
            
            for i, url in enumerate(urls):
                save_dir = output_base / ("hd" if download_mode == "hd" else "q") / date_str
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / f"temp_{int(time.time())}_{i}"
                
                success, img_hash = await actions.download_image(
                    page, url, str(save_path), remove_wm=remove_watermark
                )
                
                if success and img_hash:
                    final_path = save_dir / f"{img_hash}.webp"
                    downloaded_file = Path(str(save_path) + ".webp")
                    if downloaded_file.exists():
                        downloaded_file.rename(final_path)
                    
                    images_info.append({
                        "id": f"{date_str}/{img_hash}",
                        "hash": img_hash,
                        "date": date_str,
                        "format": "webp",
                        "url": url,
                    })

            if not images_info:
                return TaskResult(success=False, error="Failed to process any generated images")
            
            return TaskResult(
                success=True, 
                data={"images": images_info, "date": date_str},
                metadata={"model": model, "prompt": prompt, "download_mode": download_mode}
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return TaskResult(success=False, error=str(e))
        finally:
            tab.activity = "Idle"
