"""浏览器池异常类"""

import time
from enum import Enum


class BrowserStatus(str, Enum):
    """浏览器状态"""

    IDLE = "idle"  # 空闲
    BUSY = "busy"  # 忙碌
    PREPARING = "preparing"  # 准备环境中
    INPUTTING = "inputting"  # 正在输入/上传
    GENERATING = "generating"  # 等待生成结果
    DOWNLOADING = "downloading"  # 正在下载/处理图片
    OFFLINE = "offline"  # 下线(检修)
    ERROR = "error"  # 错误
    STARTING = "starting"
    STOPPED = "stopped"


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
