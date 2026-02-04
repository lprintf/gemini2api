import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Any, Dict
from playwright.async_api import Page
from .base import BaseEngineTask, TaskResult
from .. import actions

class ImageGenerationTask(BaseEngineTask):
    """图片生成与编辑任务"""
    
    # --- 选择器定义 ---
    INPUT_BOX = 'div[contenteditable="true"]'
    SUBMIT_BUTTON = [
        'button[aria-label*="发送"]',
        'button[aria-label*="Send"]',
        'button[aria-label*="submit"]',
    ]
    UPLOAD_MENU_BUTTON = [
        'button[aria-label="打开文件上传菜单"]',
        'button[aria-label="Open file upload menu"]',
        'button[aria-label*="Add files"]',
        'button[aria-label*="上传"]',
        'button[aria-label*="upload"]',
    ]
    
    MODEL_MENU_BUTTON = '[data-test-id="bard-mode-menu-button"]'
    MODEL_OPTION_FAST = [
        '[data-test-id="bard-mode-option-fast"]',
        '[data-test-id="bard-mode-option-快速"]',
        '[data-test-id="bard-mode-option-Flash"]',
    ]
    MODEL_OPTION_PRO = [
        '[data-test-id="bard-mode-option-pro"]',
        '[data-test-id="bard-mode-option-Pro"]',
    ]
    
    TOOLS_BUTTON = [
        "button.toolbox-drawer-button",
        'button[aria-label="工具"]',
        'button[aria-label="Tools"]',
    ]
    IMAGE_GEN_OPTION = [
        "text=Create images",
        "text=生成图片",
    ]
    IMAGE_GEN_DESELECT = ".toolbox-drawer-item-deselect-button"
    
    RESPONSE_CONTAINER = [
        "model-response",
        "message-content model-response",
        "response-container",
    ]
    GENERATED_IMAGE = 'img[src*="googleusercontent"]'
    DOWNLOAD_BUTTON = [
        'button[aria-label*="下载"]',
        'button[aria-label*="Download"]',
        'button[aria-label*="保存"]',
        'button[aria-label*="Save"]',
    ]
    AVATAR_PATTERN = "/a/ACg8oc"

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
            if not await actions.prepare_environment(page, self, model=model):
                return TaskResult(success=False, error="Failed to prepare environment")
            
            if input_images:
                if not await actions.upload_images_by_paste(page, input_images, self.INPUT_BOX):
                    return TaskResult(success=False, error="Failed to upload images")
                    
            if not await actions.input_prompt(page, prompt, self.INPUT_BOX):
                return TaskResult(success=False, error="Failed to input prompt")
                
            if not await actions.submit(page, self.SUBMIT_BUTTON):
                return TaskResult(success=False, error="Failed to submit generation")
                
            if not await actions.wait_for_generation(page, timeout=120):
                await asyncio.sleep(5)
                if not await actions.wait_for_generation(page, timeout=10):
                     return TaskResult(success=False, error="Generation timeout")

            # 2. 获取预览图 URL
            image_urls = await actions.get_generated_image_urls(page, self.RESPONSE_CONTAINER)
            if not image_urls:
                return TaskResult(success=False, error="No generated images found")

            # 3. 处理下载
            images_info = []
            preview_dir = base_output_dir / "q" / date_str
            preview_dir.mkdir(parents=True, exist_ok=True)
            
            for i, url in enumerate(image_urls):
                temp_path = preview_dir / f"temp_{int(time.time())}_{i}.webp"
                success, file_hash = await actions.download_image_by_index(
                    page=page, index=i, save_path=str(temp_path),
                    container_selectors=self.RESPONSE_CONTAINER,
                    download_selectors=self.DOWNLOAD_BUTTON,
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
                        page=page, url=img_info["url"], save_path=str(temp_path),
                        download_selectors=self.DOWNLOAD_BUTTON,
                        remove_watermark=remove_watermark
                    )
                    if success:
                        final_path = hd_dir / f"{img_info['hash']}.webp"
                        temp_path.rename(final_path)
                        img_info.update({
                            "size": hd_data["size"], "dimensions": hd_data["dimensions"], "is_hd": True
                        })
            
            return TaskResult(
                success=True, 
                data={"images": images_info, "date": date_str},
                metadata={"model": model, "prompt": prompt, "download_mode": download_mode}
            )

        except Exception as e:
            return TaskResult(success=False, error=str(e))
