from playwright.async_api import Page
from .base import BaseEngineTask, TaskResult
from .. import actions

class ReinitializeTask(BaseEngineTask):
    """标签页重新初始化任务"""
    
    # 常用选择器
    AGREE_BUTTON = [
        'button:has-text("Agree")',
        'button:has-text("同意")',
        'button:has-text("I agree")',
        'button:has-text("Accept")',
        'button:has-text("接受")',
        'button:has-text("OK")',
        'button:has-text("确定")',
        '[role="dialog"] button[data-mdc-dialog-action="accept"]',
        '[role="dialog"] button.mdc-dialog__button--default',
    ]
    
    INPUT_BOX = 'div[contenteditable="true"]'
    
    async def run(self, page: Page) -> TaskResult:
        model = self.payload.get("model", "Fast")
        try:
            # 执行重新初始化逻辑，传入 self 以便 actions 获取选择器
            success = await actions.reinitialize_page(page, self, model=model)
            if success:
                return TaskResult(success=True)
            return TaskResult(success=False, error="Reinitialize failed")
        except Exception as e:
            return TaskResult(success=False, error=str(e))
