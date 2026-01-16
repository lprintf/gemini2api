"""浏览器池异常类"""

import time
from enum import Enum


class BrowserStatus(str, Enum):
    """浏览器状态"""

    IDLE = "idle"  # 空闲，可接受任务
    BUSY = "busy"  # 忙碌，正在处理任务
    DOWNLOADING_HD = "downloading_hd"  # 后台下载高清图中
    PREHEATING = "preheating"  # 预热中（准备环境）
    STARTING = "starting"  # 启动中
    STOPPING = "stopping"  # 停止中
    ERROR = "error"  # 错误状态
    STOPPED = "stopped"  # 已停止


class RateLimitExceeded(Exception):
    """速率限制异常"""

    def __init__(self, browser_id: str, limit: int, window_seconds: int, reset_at: int):
        self.browser_id = browser_id
        self.limit = limit
        self.window_seconds = window_seconds
        self.reset_at = reset_at
        self.retry_after = max(0, reset_at - int(time.time()))
        super().__init__(
            f"Browser {browser_id} rate limit exceeded. "
            f"Limit: {limit}/{window_seconds}s, Reset at: {reset_at}"
        )


class NoAvailableTabs(Exception):
    """没有可用标签页异常"""

    def __init__(self, browser_id: str, total_tabs: int):
        self.browser_id = browser_id
        self.total_tabs = total_tabs
        super().__init__(
            f"Browser {browser_id} has no available tabs (all {total_tabs} tabs are busy)"
        )
