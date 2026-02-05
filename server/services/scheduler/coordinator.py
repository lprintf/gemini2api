import asyncio
import uuid
import time
from datetime import datetime
from typing import List, Optional, Any, Dict
from server.db.database import get_db
from .pool import BrowserPool

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
        """执行图片生成/编辑完整流程 (生命周期受控于此)"""
        from ..tasks.image import ImageGenerationTask
        from ..objects.exceptions import BrowserStatus

        if not task_id:
            task_id = f"task-{uuid.uuid4().hex[:12]}"
            
        start_time = time.time()
        
        # 1. 获取可用浏览器
        from ..objects.exceptions import NoAvailableBrowsers
        browser = await self.pool.get_available_browser(preferred_model=model)
        if not browser:
            raise NoAvailableBrowsers()

        # 2. 从浏览器租借一个具体的 Tab (物理资源)
        tab = browser.get_available_tab(preferred_model=model)
        if not tab:
            # 理论上 pool.get_available_browser 已经确保了有可用 tab
            raise RuntimeError(f"Browser {browser.browser_id} has no available tabs")

        # 3. 准备执行细节
        engine_task = ImageGenerationTask(
            prompt=prompt,
            input_images=input_images,
            model=model,
            download_mode=download_mode,
            remove_watermark=remove_watermark
        )

        # 4. 【生命周期管控点】：开始执行，标记资源忙碌
        browser.record_request()
        tab.status = BrowserStatus.BUSY
        
        try:
            # 5. 注入 TabInstance 到业务 Task 中运行
            result = await engine_task.run(tab)
            
            # 统计
            if result.success:
                browser.total_tasks += 1
            else:
                browser.failed_tasks += 1

            if not result.success:
                error_msg = result.error or "Unknown engine error"
                await self._record_task_failure(task_id, error_msg, time.time() - start_time)
                return {"success": False, "error": error_msg}

            return {
                "success": True,
                "task_id": task_id,
                "images": result.data.get("images", []),
                "duration": time.time() - start_time
            }

        except Exception as e:
            await self._record_task_failure(task_id, str(e), time.time() - start_time)
            raise e
        finally:
            # 6. 【生命周期管控点】：任务结束，触发环境重置
            # 为了不增加 API 响应延迟，我们将重置逻辑放在后台执行，
            # 但在重置完成前，Tab 依然保持 BUSY 状态以防止被抢占。
            async def background_rewarm(t, m):
                try:
                    from ..tasks import actions
                    await actions.reinitialize_page(t.page, model=m)
                except Exception as e:
                    print(f"[Coordinator] Background rewarm failed: {e}")
                finally:
                    t.status = BrowserStatus.IDLE
                    t.last_active_at = datetime.now()
            
            # 启动后台重置任务，不阻塞当前请求的返回
            asyncio.create_task(background_rewarm(tab, model))

    async def _record_task_failure(self, task_id: str, error: str, duration: float):
        """记录任务失败到数据库"""
        try:
            db = get_db()
            # 假设 db 有相应方法，如果没有则先忽略或打印
            # await db.update_task_status(task_id, "failed", error=error, duration=duration)
            pass
        except:
            pass
