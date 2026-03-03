"""浏览器池异常类"""

import time
from enum import Enum


class BrowserStatus(str, Enum):
    """浏览器状态"""

    IDLE = "idle"  # 可用
    BUSY = "busy"  # 忙碌
    DISABLED = "disabled" # 禁用(不接活)
    ERROR = "error"  # 故障
    LAUNCHING = "launching" # 启动中
    CLOSING = "closing" # 关闭中
    CLOSED = "closed"   # 已关闭
    SLEEP = "sleep"     # 休眠中 (限额冷却)


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


class NoAvailableBrowsers(Exception):
    """没有可用浏览器异常"""

    def __init__(self):
        super().__init__("No available browsers (all instances are busy or offline)")
