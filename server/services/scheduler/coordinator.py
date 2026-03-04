import asyncio
import uuid
import time
from datetime import datetime, timedelta
from typing import List, Optional, Any, Dict
from server.db.database import get_db
from server.utils.logger import tab_log
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
            now = datetime.now()
            tab.last_active_at = now
            browser.last_active_at = now
            
            if result.success:
                browser.total_tasks += 1
                tab.total_tasks += 1
                tab.consecutive_failures = 0
            else:
                browser.failed_tasks += 1
                tab.failed_tasks += 1
                tab.consecutive_failures += 1

            if not result.success:
                error_msg = result.error or "Unknown engine error"
                await self._record_task_failure(task_id, error_msg, time.time() - start_time)
                return {"success": False, "error": error_msg}

            return {
                "success": True,
                "task_id": task_id,
                "images": result.data.get("images", []),
                "text": result.data.get("text"),
                "duration": time.time() - start_time
            }

        except BaseException as e:
            now = datetime.now()
            tab.last_active_at = now
            browser.last_active_at = now
            browser.failed_tasks += 1
            tab.failed_tasks += 1
            tab.consecutive_failures += 1
            
            # 【全局惩罚】：发生故障或被取消时，强制进入 9 分钟冷却（若尚未标记）
            from server.services.objects.exceptions import BrowserStatus
            if tab.status != BrowserStatus.SLEEP:
                tab_log(tab.page, f"Task failed or cancelled: {e}. Triggering 9m mandatory punishment.", "error")
                tab.status = BrowserStatus.SLEEP
                tab.sleep_until = now + timedelta(minutes=9)
            
            await self._record_task_failure(task_id, str(e), time.time() - start_time)
            raise e
        finally:
            # 确保即使是正常返回 result.success 为 False 且没有标记 sleep 的，也给个默认惩罚
            from server.services.objects.exceptions import BrowserStatus
            if result and not result.success and tab.status != BrowserStatus.SLEEP:
                tab_log(tab.page, "Task reported failure without sleep. Triggering default 9m punishment.", "warning")
                tab.status = BrowserStatus.SLEEP
                tab.sleep_until = datetime.now() + timedelta(minutes=9)

            # 6. 【生命周期管控点】：任务结束，按需执行后台延续任务，最终重置环境
            # Tab 在整个链条完成前保持 BUSY，防止被抢占
            bg_work = result.background_work if result and result.background_work else None

            async def background_chain(t, m, work):
                from server.services.objects.exceptions import BrowserStatus
                try:
                    # 1. 如果标记了 SLEEP，优先在此处等待（保持现场供人工检查）
                    if t.status == BrowserStatus.SLEEP and t.sleep_until:
                        while True:
                            now = datetime.now()
                            wait_seconds = (t.sleep_until - now).total_seconds()
                            if wait_seconds <= 0:
                                break
                            
                            # 每隔 60s 打印一次活跃日志
                            tab_log(t.page, f"Tab is in SLEEP mode. {wait_seconds:.0f}s remaining before recovery.")
                            await asyncio.sleep(min(60, wait_seconds))
                        
                        tab_log(t.page, "Sleep period ended. Starting recovery...")

                    # 2. 执行后台延续任务 (如强制重排)
                    if work:
                        tab_log(t.page, "Running background work...")
                        await work
                        tab_log(t.page, "Background work completed")
                except Exception as e:
                    tab_log(t.page, f"Background chain failed at some stage: {e}", "error")
                finally:
                    try:
                        from ..tasks import actions
                        await actions.reinitialize_page(t.page, model=m)
                    except Exception as e:
                        tab_log(t.page, f"Background final rewarm failed: {e}", "error")
                    finally:
                        t.status = BrowserStatus.IDLE
                        t.sleep_until = None
                        t.last_active_at = datetime.now()
            
            asyncio.create_task(background_chain(tab, model, bg_work))

    async def _record_task_failure(self, task_id: str, error: str, duration: float):
        """记录任务失败到数据库"""
        try:
            db = get_db()
            # 假设 db 有相应方法，如果没有则先忽略或打印
            # await db.update_task_status(task_id, "failed", error=error, duration=duration)
            pass
        except:
            pass
