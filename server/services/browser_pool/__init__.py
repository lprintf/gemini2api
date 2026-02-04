"""
浏览器池管理器

负责管理多个浏览器实例，每个实例：
- 使用独立的 user_data_dir
- 可以配置独立的代理
- 可以登录不同的 Google 账号
- 支持负载均衡
- 支持浏览器级别的速率限制
- 支持 SQLite 数据库持久化
"""

from .gemini import BrowserInstance
from .exceptions import BrowserStatus, NoAvailableTabs, RateLimitExceeded
from .pool import BrowserPool
from .tab import TabInstance

__all__ = [
    "BrowserPool",
    "BrowserInstance",
    "TabInstance",
    "BrowserStatus",
    "RateLimitExceeded",
    "NoAvailableTabs",
]
