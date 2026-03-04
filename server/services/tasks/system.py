from datetime import datetime, timedelta
from playwright.async_api import Page
from .base import BaseEngineTask, TaskResult
from . import actions
from ..objects.exceptions import BrowserStatus

class ReinitializeTask(BaseEngineTask):
    """标签页重新初始化任务 (逻辑编排层)"""
    
    async def run(self, tab: Any) -> TaskResult:
        import time
        page = tab.page
        model = self.payload.get("model", "Fast")
        start_ts = time.time()
        try:
            # 仅仅调用原子的/流式的 Action
            success = await actions.reinitialize_page(page, model=model)
            if success:
                return TaskResult(success=True)
            
            # 逻辑失败也记录下快照
            await actions.dump_inspect(page, mode="full")
            await actions.dump_html(page)
            tab.status = BrowserStatus.SLEEP
            tab.sleep_until = datetime.now() + timedelta(minutes=9)
            return TaskResult(success=False, error="Reinitialize failed")
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            from server.utils.logger import tab_log
            tab_log(page, f"Reinitialize fatal error: {str(e)}\n{error_trace}", "error")
            try:
                await actions.dump_inspect(page, mode="full")
                await actions.dump_html(page)
            except: pass
            
            tab.status = BrowserStatus.SLEEP
            tab.sleep_until = datetime.now() + timedelta(minutes=9)
            return TaskResult(success=False, error=str(e))
        finally:
            duration = round(time.time() - start_ts, 3)
            from server.utils.logger import tab_log
            tab_log(page, f"Reinitialize finished in {duration}s")
