from playwright.async_api import Page
from .base import BaseEngineTask, TaskResult
from . import actions

class ReinitializeTask(BaseEngineTask):
    """标签页重新初始化任务 (逻辑编排层)"""
    
    async def run(self, page: Page) -> TaskResult:
        model = self.payload.get("model", "Fast")
        try:
            # 仅仅调用原子的/流式的 Action
            success = await actions.reinitialize_page(page, model=model)
            if success:
                return TaskResult(success=True)
            return TaskResult(success=False, error="Reinitialize failed")
        except Exception as e:
            return TaskResult(success=False, error=str(e))
