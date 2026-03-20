import asyncio
import uuid
import time
from datetime import datetime, timedelta
from typing import List, Optional, Any, Dict
from server.db.database import get_db
from server.db.models import TaskRecord
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
        task_id: Optional[str] = None,
        is_disconnected: Optional[Any] = None # Optional callable to check client state
    ) -> Dict[str, Any]:
        """执行图片生成/编辑完整流程 (生命周期受控于此)"""
        from ..tasks.image import ImageGenerationTask
        from ..objects.exceptions import BrowserStatus

        if not task_id:
            task_id = f"task-{uuid.uuid4().hex[:12]}"
            
        start_time = time.time()
        db = get_db()
        browser = None
        tab = None
        result = None
        
        try:
            # 1. 尝试获取可用 Tab (设置 0s 超时，即立即失败触发 429)
            from ..objects.exceptions import NoAvailableBrowsers, NoAvailableTabs
            tab = await self.pool.acquire_tab(model=model, timeout=0.0)
            browser = self.pool.get_browser(tab.browser_id)
            if not browser:
                raise RuntimeError(f"Browser {tab.browser_id} for acquired tab not found")

            # 2. 只有拿到 Tab 后，才正式在数据库中创建任务记录 (防止 429 的任务污染数据库)
            task_record = TaskRecord(
                task_id=task_id,
                prompt=prompt,
                model=model,
                input_image=str(input_images[0]) if input_images else None,
                status="processing",
                created_at=datetime.now()
            )
            await db.create_task(task_record)

            # 3. 立即记录分配的资源
            await db.update_task(task_id, {
                "browser_id": tab.browser_id,
                "tab_id": tab.tab_id
            })

            # 4. 准备执行细节
            engine_task = ImageGenerationTask(
                prompt=prompt,
                input_images=input_images,
                model=model,
                download_mode=download_mode,
                remove_watermark=remove_watermark,
                is_disconnected=is_disconnected
            )

            # 5. 【生命周期管控点】：开始执行，标记资源忙碌
            # 注意：此处不再显式 record_request，依靠 FIFO 天然轮换
            tab.status = BrowserStatus.BUSY
            
            # 6. 注入 TabInstance 到业务 Task 中运行
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
                duration = time.time() - start_time
                await db.update_task(task_id, {
                    "status": "failed",
                    "error_message": error_msg,
                    "duration": duration,
                    "completed_at": datetime.now()
                })
                return {"success": False, "error": error_msg}

            duration = time.time() - start_time
            result_paths = []
            for img in result.data.get("images", []):
                result_paths.append(img.get("id"))

            await db.update_task(task_id, {
                "status": "completed",
                "result_paths": result_paths,
                "duration": duration,
                "completed_at": datetime.now()
            })

            return {
                "success": True,
                "task_id": task_id,
                "images": result.data.get("images", []),
                "text": result.data.get("text"),
                "duration": duration
            }

        except (NoAvailableBrowsers, NoAvailableTabs) as e:
            # 资源不足直接透传，由 API 层转为 429
            # 因为没有落库任务记录，我们直接抛出，彻底不在数据库里分配该任务
            raise e
        except BaseException as e:
            now = datetime.now()
            # 如果 browser/tab 已准备好，则进行惩罚
            if tab:
                tab.last_active_at = now
                browser.last_active_at = now
                browser.failed_tasks += 1
                tab.failed_tasks += 1
                tab.consecutive_failures += 1
                
                # 【全局惩罚】：发生故障时，强制进入 9 分钟冷却（若尚未标记）
                # 注意：如果是 asyncio.CancelledError (Client disconnected)，不记录严厉惩罚，仅让其 rewarm
                from server.services.objects.exceptions import BrowserStatus
                if isinstance(e, asyncio.CancelledError):
                    tab_log(tab.page, f"Task cancelled by client: {e}. Skipping 9m penalty, triggering rewarm.", "warning")
                elif tab.status != BrowserStatus.SLEEP:
                    tab_log(tab.page, f"Task failed with error: {e}. Triggering 9m mandatory punishment.", "error")
                    tab.status = BrowserStatus.SLEEP
                    tab.sleep_until = now + timedelta(minutes=9)
            
            duration = time.time() - start_time
            await db.update_task(task_id, {
                "status": "failed",
                "error_message": str(e),
                "duration": duration,
                "completed_at": datetime.now()
            })
            raise e
        finally:
            # 只有在 tab 存在的情况下才执行 background_chain
            if tab:
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
                    # === 核心调度逻辑：处理惩罚、恢复与回笼 ===
                    try:
                        # 1. 如果处于 SLEEP 状态（如触发了 9m 惩罚），在此处挂起并保持现场
                        if t.status == BrowserStatus.SLEEP and t.sleep_until:
                            while True:
                                now = datetime.now()
                                wait_seconds = (t.sleep_until - now).total_seconds()
                                if wait_seconds <= 0:
                                    break
                                tab_log(t.page, f"Tab is in SLEEP mode. {wait_seconds:.0f}s remaining before recovery.")
                                await asyncio.sleep(min(60, wait_seconds))
                            tab_log(t.page, "Sleep period ended. Starting recovery...")

                        # 2. 如果有后台工作（如 HD 下载等），在此执行
                        if work:
                            tab_log(t.page, "Running background work...")
                            await work
                            tab_log(t.page, "Background work completed")

                        # 3. 准备回笼：只要没死，就尝试洗白
                        t.last_active_at = datetime.now()
                        if t.status == BrowserStatus.CLOSED or getattr(t, "page", None) is None:
                            tab_log(t.page, f"Tab {t.tab_id} is dead ({t.status}), skipping re-entry.", "warning")
                            return

                        from ..tasks import actions
                        success = await actions.reinitialize_page(t.page, model=m)
                        if success:
                            # release_tab 会自动处理 status = IDLE
                            await self.pool.release_tab(t)
                        else:
                            t.status = BrowserStatus.ERROR
                            tab_log(t.page, f"Tab {t.tab_id} re-warm failed, abandoned.", "warning")
                    except Exception as e:
                        tab_log(t.page, f"Fatal error in background chain: {e}", "error")
                        t.status = BrowserStatus.ERROR
                
                asyncio.create_task(background_chain(tab, model, bg_work))
