"""标签页实例 (Data Object)"""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from .exceptions import BrowserStatus


class TabInstance:
    """标签页实例 - 仅作为状态容器"""

    def __init__(self, tab_id: int, browser_id: str, preferred_model: str = "Fast"):
        self.tab_id = tab_id
        self.browser_id = browser_id
        self.page: Any = None  # Playwright Page 对象
        self.status = BrowserStatus.STARTING
        self.preferred_model = preferred_model
        
        self.current_task_id: Optional[str] = None
        self.total_tasks = 0
        self.failed_tasks = 0
        self.consecutive_failures = 0
        self.last_active_at: Optional[datetime] = None
        
        # 任务相关中间状态
        self.hd_metadata: Optional[Dict[str, Any]] = None
        self.hd_download_task: Optional[asyncio.Task] = None

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "tab_id": self.tab_id,
            "browser_id": self.browser_id,
            "preferred_model": self.preferred_model,
            "status": self.status.value,
            "total_tasks": self.total_tasks,
            "failed_tasks": self.failed_tasks,
            "current_task_id": self.current_task_id,
            "last_active_at": self.last_active_at.isoformat() if self.last_active_at else None,
        }
