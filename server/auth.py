"""
身份认证模块

使用 HTTP Basic Auth 保护管理接口
"""

import os
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from server.config import get_config

security = HTTPBasic()


async def verify_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """
    验证管理员身份

    使用 HTTP Basic Auth，优先级：环境变量 > 数据库配置 > 默认值

    环境变量：
    - ADMIN_USERNAME: 管理员用户名
    - ADMIN_PASSWORD: 管理员密码
    """
    # 优先从环境变量读取
    correct_username = os.getenv("ADMIN_USERNAME")
    correct_password = os.getenv("ADMIN_PASSWORD")

    # 如果环境变量未设置，尝试从配置读取
    if not correct_username or not correct_password:
        try:
            config = get_config()
            correct_username = correct_username or config.security.admin_username
            correct_password = correct_password or config.security.admin_password
        except Exception:
            # 如果配置未初始化，使用默认值
            correct_username = correct_username or "admin"
            correct_password = correct_password or "changeme"

    # 使用常量时间比较，防止时序攻击
    is_username_correct = secrets.compare_digest(
        credentials.username.encode("utf8"),
        correct_username.encode("utf8")
    )
    is_password_correct = secrets.compare_digest(
        credentials.password.encode("utf8"),
        correct_password.encode("utf8")
    )

    if not (is_username_correct and is_password_correct):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
