import asyncio
import uuid
import time
from typing import List, Optional, Any, Dict
from server.db.database import get_db
from .browser_pool.pool import BrowserPool

class TaskCoordinator:
    """任务协调者：负责资源调度、执行引擎任务以及业务层的数据记录"""
    
    def __init__(self, pool: BrowserPool):
        self.pool = pool

    async def generate_images(
        self,
        prompt: str,
        input_images: List[str] = [],
        model: str = "Fast",
        download_mode: str = "preview", # preview, hd, both
        remove_watermark: bool = True,
        task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """执行图片生成/编辑完整流程"""
        from server.engine.tasks.image_tasks import ImageGenerationTask

        if not task_id:
            task_id = f"task-{uuid.uuid4().hex[:12]}"
            
        start_time = time.time()
        
        # 1. 获取可用浏览器
        browser = await self.pool.get_available_browser(preferred_model=model)
        if not browser:
            raise RuntimeError("No available browsers")

        # 2. 封装引擎任务 (封装了自动化和基本的下载逻辑)
        engine_task = ImageGenerationTask(
            prompt=prompt,
            input_images=input_images,
            model=model,
            download_mode=download_mode,
            remove_watermark=remove_watermark
        )

        try:
            # 3. 执行任务
            result = await browser.run_task(engine_task, preferred_model=model)
            
            if not result.success:
                error_msg = result.error or "Unknown engine error"
                await self._record_task_failure(task_id, error_msg, time.time() - start_time)
                return {"success": False, "error": error_msg}

            # 4. 成功后记录到数据库 (可选，看目前的 DB 实现)
            # result.data 通常包含 {"images": [...], "date": "..."}
            images = result.data.get("images", [])
            
            return {
                "success": True,
                "task_id": task_id,
                "images": images,
                "duration": time.time() - start_time
            }

        except Exception as e:
            await self._record_task_failure(task_id, str(e), time.time() - start_time)
            raise e

    async def _record_task_failure(self, task_id: str, error: str, duration: float):
        """记录任务失败到数据库"""
        try:
            db = get_db()
            # 假设 db 有相应方法，如果没有则先忽略或打印
            # await db.update_task_status(task_id, "failed", error=error, duration=duration)
            pass
        except:
            pass
