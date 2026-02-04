import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Any, Dict
from playwright.async_api import Page
from .base import BaseEngineTask, TaskResult
from .. import actions

class ImageGenerationTask(BaseEngineTask):
    """图片生成与编辑任务（包含下载与可选后台下载逻辑）"""
    
    async def run(self, page: Page) -> TaskResult:
        prompt = self.payload.get("prompt")
        input_images = self.payload.get("input_images", [])
        if not input_images and self.payload.get("input_image"):
            input_images = [self.payload.get("input_image")]
            
        model = self.payload.get("model", "Fast")
        output_dir = self.payload.get("output_dir", "data/outputs")
        remove_watermark = self.payload.get("remove_watermark", True)
        download_mode = self.payload.get("download_mode", "preview") # preview, hd, both
        
        base_output_dir = Path(output_dir)
        date_str = datetime.now().strftime("%Y%m%d")
        
        try:
            # 1. Pipeline 逻辑
            if not await actions.prepare_environment(page, model=model):
                return TaskResult(success=False, error="Failed to prepare environment")
            
            if input_images:
                if not await actions.upload_images_by_paste(page, input_images):
                    return TaskResult(success=False, error="Failed to upload images")
                    
            if not await actions.input_prompt(page, prompt):
                return TaskResult(success=False, error="Failed to input prompt")
                
            if not await actions.submit(page):
                return TaskResult(success=False, error="Failed to submit generation")

            if not await actions.wait_for_generation(page, timeout=120):
                await asyncio.sleep(5)
                if not await actions.wait_for_generation(page, timeout=10):
                     return TaskResult(success=False, error="Generation timeout")

            # 2. 获取预览图 URL
            image_urls = await actions.get_generated_image_urls(page)
            if not image_urls:
                return TaskResult(success=False, error="No generated images found")

            # 3. 处理下载
            images_info = []
            
            # 始终下载预览图（快速）
            preview_dir = base_output_dir / "q" / date_str
            preview_dir.mkdir(parents=True, exist_ok=True)
            for i, url in enumerate(image_urls):
                temp_path = preview_dir / f"temp_{int(time.time())}_{i}.webp"
                success, file_hash = await actions.download_image_by_index(
                    page=page, index=i, save_path=str(temp_path),
                    remove_watermark=remove_watermark, skip_hd=True
                )
                if success and file_hash:
                    final_path = preview_dir / f"{file_hash}.webp"
                    temp_path.rename(final_path)
                    images_info.append({
                        "index": i, "hash": file_hash, "id": f"{date_str}/{file_hash}",
                        "date": date_str, "format": "webp", "path": str(final_path),
                        "size": final_path.stat().st_size if final_path.exists() else 0,
                        "url": url,
                    })

            if not images_info:
                return TaskResult(success=False, error="Failed to download any images")

            # 4. 如果是 同步 HD，则现在下载
            if download_mode == "hd":
                hd_dir = base_output_dir / "hd" / date_str
                hd_dir.mkdir(parents=True, exist_ok=True)
                for img_info in images_info:
                    temp_path = hd_dir / f"temp_sync_{img_info['hash']}.webp"
                    success, hd_data = await actions.download_hd_by_url(
                        page=page, url=img_info["url"], save_path=str(temp_path), remove_watermark=remove_watermark
                    )
                    if success:
                        final_path = hd_dir / f"{img_info['hash']}.webp"
                        temp_path.rename(final_path)
                        img_info.update({
                            "size": hd_data["size"], "dimensions": hd_data["dimensions"], "is_hd": True
                        })

            # 5. 如果是 both，则返回当前结果，并由外界触发后台 HD (或者在该 Task 结束前的回调中处理)
            # 在目前的 run_task 模型中，我们暂时让 both 由调用者决定是否需要继续占用资源
            # 或者我们在这里创建一个后台协程，并修改 BrowserInstance 以支持异步状态管理
            
            return TaskResult(
                success=True, 
                data={"images": images_info, "date": date_str},
                metadata={"model": model, "prompt": prompt, "download_mode": download_mode}
            )

        except Exception as e:
            return TaskResult(success=False, error=str(e))
