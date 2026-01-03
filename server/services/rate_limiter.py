"""
速率限制器

基于滑动窗口算法，防止 API 滥用
"""

import time
from collections import deque
from typing import Dict, Optional


class RateLimiter:
    """速率限制器"""

    def __init__(self, default_limit: int = 10, window_seconds: int = 60):
        """
        Args:
            default_limit: 默认速率限制（请求数/窗口时间）
            window_seconds: 时间窗口（秒）
        """
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        self._requests: Dict[str, deque] = {}  # {client_id: deque([timestamp, ...])}

    def check_rate_limit(
        self,
        client_id: str,
        limit: Optional[int] = None
    ) -> tuple[bool, Dict]:
        """
        检查是否超过速率限制

        Args:
            client_id: 客户端标识（IP、API Key 等）
            limit: 自定义限制（如果为 None 则使用默认值）

        Returns:
            (是否允许, 限制信息)
        """
        limit = limit or self.default_limit
        current_time = time.time()

        # 初始化客户端请求记录
        if client_id not in self._requests:
            self._requests[client_id] = deque()

        # 清理过期请求
        requests = self._requests[client_id]
        while requests and requests[0] < current_time - self.window_seconds:
            requests.popleft()

        # 检查是否超限
        remaining = limit - len(requests)
        allowed = remaining > 0

        info = {
            "limit": limit,
            "remaining": max(0, remaining),
            "reset": int(current_time + self.window_seconds),
            "window_seconds": self.window_seconds,
        }

        return allowed, info

    def record_request(self, client_id: str):
        """记录请求"""
        current_time = time.time()

        if client_id not in self._requests:
            self._requests[client_id] = deque()

        self._requests[client_id].append(current_time)

    def get_client_stats(self, client_id: str) -> Dict:
        """获取客户端统计信息"""
        current_time = time.time()

        if client_id not in self._requests:
            return {
                "total_requests": 0,
                "requests_in_window": 0,
                "oldest_request": None,
                "newest_request": None,
            }

        requests = self._requests[client_id]

        # 清理过期请求
        while requests and requests[0] < current_time - self.window_seconds:
            requests.popleft()

        return {
            "total_requests": len(requests),
            "requests_in_window": len(requests),
            "oldest_request": requests[0] if requests else None,
            "newest_request": requests[-1] if requests else None,
        }

    def reset_client(self, client_id: str):
        """重置客户端限制"""
        if client_id in self._requests:
            del self._requests[client_id]

    def get_all_clients(self) -> list[str]:
        """获取所有客户端 ID"""
        return list(self._requests.keys())
