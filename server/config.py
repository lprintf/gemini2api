"""
配置管理

支持从 SQLite 数据库和环境变量加载配置
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from .core.database import get_db
from .core.models import GlobalConfig


class ServerConfig(BaseModel):
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    reload: bool = False


class BrowserPoolConfig(BaseModel):
    """浏览器池配置"""
    min_browsers: int = 1
    max_browsers: int = 10
    idle_timeout: int = 300  # 秒
    health_check_interval: int = 60  # 秒
    default_headless: bool = True


class RateLimitConfig(BaseModel):
    """速率限制配置"""
    default_limit: int = 10  # 每分钟请求数
    window_seconds: int = 60
    burst: int = 20


class LoadBalancerConfig(BaseModel):
    """负载均衡配置"""
    strategy: str = "least_loaded"  # round_robin/least_loaded/random


class LoggingConfig(BaseModel):
    """日志配置"""
    level: str = "INFO"
    file: str = "data/logs/app.log"
    max_size: str = "100MB"
    backup_count: int = 10


class SecurityConfig(BaseModel):
    """安全配置"""
    admin_username: str = "admin"
    admin_password: str = "changeme"
    jwt_secret: str = "your-secret-key-change-in-production"
    cors_origins: list[str] = ["*"]
    api_key_header: str = "Authorization"


class Config(BaseModel):
    """全局配置"""
    server: ServerConfig = ServerConfig()
    browser_pool: BrowserPoolConfig = BrowserPoolConfig()
    rate_limit: RateLimitConfig = RateLimitConfig()
    load_balancer: LoadBalancerConfig = LoadBalancerConfig()
    logging: LoggingConfig = LoggingConfig()
    security: SecurityConfig = SecurityConfig()


def apply_env_overrides(config: Config) -> Config:
    """应用环境变量覆盖"""
    env_mappings = {
        "SERVER_HOST": ("server", "host", str),
        "SERVER_PORT": ("server", "port", int),
        "MAX_BROWSERS": ("browser_pool", "max_browsers", int),
        "MIN_BROWSERS": ("browser_pool", "min_browsers", int),
        "DEFAULT_HEADLESS": ("browser_pool", "default_headless", lambda x: x.lower() == "true"),
        "RATE_LIMIT": ("rate_limit", "default_limit", int),
        "RATE_WINDOW": ("rate_limit", "window_seconds", int),
        "LB_STRATEGY": ("load_balancer", "strategy", str),
        "LOG_LEVEL": ("logging", "level", str),
        "ADMIN_USERNAME": ("security", "admin_username", str),
        "ADMIN_PASSWORD": ("security", "admin_password", str),
        "JWT_SECRET": ("security", "jwt_secret", str),
    }

    for env_var, (section, field, converter) in env_mappings.items():
        value = os.getenv(env_var)
        if value is not None:
            section_obj = getattr(config, section)
            setattr(section_obj, field, converter(value))

    # 特殊处理 CORS_ORIGINS (逗号分隔)
    cors_origins = os.getenv("CORS_ORIGINS")
    if cors_origins:
        config.security.cors_origins = [o.strip() for o in cors_origins.split(",")]

    return config


def config_from_global(global_config: GlobalConfig) -> Config:
    """从数据库全局配置创建 Config 对象"""
    return Config(
        server=ServerConfig(
            host=global_config.server_host,
            port=global_config.server_port,
        ),
        browser_pool=BrowserPoolConfig(
            min_browsers=global_config.min_browsers,
            max_browsers=global_config.max_browsers,
            default_headless=global_config.default_headless,
        ),
        rate_limit=RateLimitConfig(
            default_limit=global_config.default_rate_limit,
            window_seconds=global_config.rate_window_seconds,
        ),
        load_balancer=LoadBalancerConfig(
            strategy=global_config.lb_strategy,
        ),
        logging=LoggingConfig(
            level=global_config.log_level,
        ),
        security=SecurityConfig(
            admin_username=global_config.admin_username,
            admin_password=global_config.admin_password,
            cors_origins=global_config.cors_origins,
        ),
    )


# 全局配置实例
_config: Optional[Config] = None


async def init_config_from_db() -> Config:
    """从数据库初始化配置"""
    global _config
    db = get_db()
    global_config = await db.get_global_config()
    _config = config_from_global(global_config)
    _config = apply_env_overrides(_config)
    return _config


def init_config_sync(global_config: Optional[GlobalConfig] = None) -> Config:
    """同步初始化配置（用于启动时）"""
    global _config
    if global_config:
        _config = config_from_global(global_config)
    else:
        _config = Config()
    _config = apply_env_overrides(_config)
    return _config


def get_config() -> Config:
    """获取全局配置"""
    if _config is None:
        raise RuntimeError("Config not initialized. Call init_config_from_db() first.")
    return _config


async def reload_config() -> Config:
    """重新加载配置"""
    return await init_config_from_db()
