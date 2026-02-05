import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Any, Dict
from playwright.async_api import Page
from .base import BaseEngineTask, TaskResult
from . import actions

class ImageGenerationTask(BaseEngineTask):
    """图片生成与编辑任务（逻辑编排层）"""
    
    async def run(self, page: Page) -> TaskResult:
        # 1. 提取参数
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
            # 2. 编排 Page 行为 (Actions 排列组合)
            if not await actions.prepare_environment(page, model=model):
                return TaskResult(success=False, error="Failed to prepare environment")
            
            # 上传图片
            for img_path in input_images:
                if not await actions.upload_image(page, img_path):
                    return TaskResult(success=False, error=f"Failed to upload image: {img_path}")
            
            # 输入提示词
            if not await actions.input_prompt(page, prompt):
                return TaskResult(success=False, error="Failed to input prompt")
                
            # 提交
            if not await actions.click_submit(page):
                return TaskResult(success=False, error="Failed to click submit")
                
            # 等待生成
            if not await actions.wait_for_results(page, timeout_s=120):
                return TaskResult(success=False, error="Generation timeout")

            # 3. 获取结果 URL
            image_urls = await actions.get_generated_urls(page)
            if not image_urls:
                return TaskResult(success=False, error="No generated images found in response")

            # 4. 下载处理
            images_info = []
            preview_dir = base_output_dir / "q" / date_str
            preview_dir.mkdir(parents=True, exist_ok=True)
            
            for i, url in enumerate(image_urls):
                temp_name = f"temp_{int(time.time())}_{i}"
                save_path = str(preview_dir / temp_name)
                
                # 执行下载 (Action 内部处理 HD/Preview 降级逻辑)
                # 注意：Task 控制逻辑：如果 download_mode 是 hd，这里实际上已经是由 action 尝试 hd 了
                success, file_hash = await actions.download_image(
                    page=page, 
                    img_url=url, 
                    save_path=save_path,
                    remove_wm=remove_watermark
                )
                
                if success and file_hash:
                    final_path = preview_dir / f"{file_hash}.webp"
                    Path(save_path).with_suffix(".webp").rename(final_path)
                    
                    images_info.append({
                        "index": i, 
                        "hash": file_hash, 
                        "id": f"{date_str}/{file_hash}",
                        "date": date_str, 
                        "format": "webp",
                        "size": final_path.stat().st_size,
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
            return TaskResult(success=False, error=str(e))
