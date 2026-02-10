from typing import Any, Dict, Optional
from playwright.async_api import Page
from pydantic import BaseModel

class TaskResult(BaseModel):
    """统一的任务执行结果"""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = {}
    # 可选的后台延续任务（如 both 模式下的 HD 下载），不阻塞客户端返回
    background_work: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True

from ..objects.exceptions import BrowserStatus
# 我们在运行时动态注入 tab 

class BaseEngineTask:
    """Gemini 引擎任务基类"""
    def __init__(self, **kwargs):
        self.payload = kwargs

    async def run(self, tab: Any) -> TaskResult:
        """任务执行逻辑（由子类实现）"""
        raise NotImplementedError
