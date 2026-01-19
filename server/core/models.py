"""
Pydantic models for database entities
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class BrowserConfig(BaseModel):
    """浏览器配置模型"""

    id: Optional[int] = None
    browser_id: str
    account_name: str
    proxy: Optional[str] = None
    headless: bool = True
    user_data_dir: str
    rate_limit: int = 2
    rate_window: int = 30
    is_enabled: bool = True
    auto_start: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class BrowserConfigCreate(BaseModel):
    """创建浏览器的请求模型"""

    browser_id: Optional[int] = None  # 可选，自动分配
    account_name: Optional[str] = None  # 可选，默认等于 browser_id
    proxy: Optional[str] = None
    headless: bool = True
    auto_start: bool = True


class BrowserConfigUpdate(BaseModel):
    """更新浏览器的请求模型"""

    account_name: Optional[str] = None
    proxy: Optional[str] = None
    headless: Optional[bool] = None
    rate_limit: Optional[int] = None
    rate_window: Optional[int] = None
    is_enabled: Optional[bool] = None
    auto_start: Optional[bool] = None


class TaskRecord(BaseModel):
    """任务记录模型"""

    id: Optional[int] = None
    task_id: str
    browser_id: Optional[str] = None
    prompt: str
    model: str = "Fast"
    input_image: Optional[str] = None
    status: str = "pending"  # pending/processing/completed/failed
    result_paths: Optional[List[str]] = None
    error_message: Optional[str] = None
    duration: Optional[float] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GlobalConfig(BaseModel):
    """全局配置模型"""

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    # Browser Pool
    min_browsers: int = 1
    max_browsers: int = 10
    default_headless: bool = True
    # Rate Limit
    default_rate_limit: int = 6
    rate_window_seconds: int = 60
    # Load Balancer
    lb_strategy: str = "least_loaded"  # round_robin/least_loaded/random
    # Logging
    log_level: str = "INFO"
    # Security
    admin_username: str = "admin"
    admin_password: str = "changeme"
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])
    # Metadata
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GlobalConfigUpdate(BaseModel):
    """更新全局配置的请求模型"""

    server_host: Optional[str] = None
    server_port: Optional[int] = None
    min_browsers: Optional[int] = None
    max_browsers: Optional[int] = None
    default_headless: Optional[bool] = None
    default_rate_limit: Optional[int] = None
    rate_window_seconds: Optional[int] = None
    lb_strategy: Optional[str] = None
    log_level: Optional[str] = None
    admin_username: Optional[str] = None
    admin_password: Optional[str] = None
    cors_origins: Optional[List[str]] = None


class EventLog(BaseModel):
    """事件日志模型"""

    id: Optional[int] = None
    browser_id: Optional[str] = None
    level: str  # DEBUG/INFO/WARNING/ERROR
    message: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskStats(BaseModel):
    """任务统计模型"""

    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    pending_tasks: int = 0
    processing_tasks: int = 0
    today_tasks: int = 0
    today_completed: int = 0
    today_failed: int = 0
    avg_duration: Optional[float] = None


class BrowserStatus(BaseModel):
    """浏览器状态响应模型"""

    browser_id: str
    account_name: str
    proxy: Optional[str] = None
    headless: bool = True
    status: str  # idle/busy/starting/stopping/error/stopped
    user_data_dir: str
    is_enabled: bool = True
    auto_start: bool = True
    rate_limit: int = 6
    rate_window: int = 60
    created_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    total_tasks: int = 0
    failed_tasks: int = 0
    current_task_id: Optional[str] = None
    rate_limit_info: Optional[dict] = None
