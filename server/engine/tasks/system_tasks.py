from .base import BaseEngineTask, TaskResult
from .. import actions
from playwright.async_api import Page

class ReinitializeTask(BaseEngineTask):
    """标签页重新初始化任务"""
    
    async def run(self, page: Page) -> TaskResult:
        model = self.payload.get("model", "Fast")
        try:
            success = await actions.reinitialize_page(page, model=model)
            if success:
                return TaskResult(success=True)
            return TaskResult(success=False, error="Reinitialize failed")
        except Exception as e:
            return TaskResult(success=False, error=str(e))
