"""
管理 API

用于管理浏览器、配置、任务、日志等
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from server.services.browser_pool import BrowserPool
from server.core.database import get_db
from server.core.models import (
    BrowserConfigCreate,
    BrowserConfigUpdate,
    GlobalConfigUpdate,
)


router = APIRouter(prefix="/api/admin", tags=["Management"])


# 全局变量（由 app.py 初始化）
browser_pool: Optional[BrowserPool] = None


class CreateBrowserRequest(BaseModel):
    """创建浏览器请求"""
    browser_id: Optional[int] = None  # 可选的浏览器 ID，不提供则自动分配
    account_name: Optional[str] = None  # 可选的账号名称，默认等于 ID
    proxy: Optional[str] = None
    headless: bool = True
    auto_start: bool = True
    max_tabs: int = 6  # 最大标签页数量


class UpdateBrowserRequest(BaseModel):
    """更新浏览器请求"""
    account_name: Optional[str] = None
    proxy: Optional[str] = None
    headless: Optional[bool] = None
    rate_limit: Optional[int] = None
    rate_window: Optional[int] = None
    is_enabled: Optional[bool] = None
    auto_start: Optional[bool] = None


class BrowserResponse(BaseModel):
    """浏览器响应"""
    browser_id: str
    account_name: str
    proxy: Optional[str]
    status: str
    total_tasks: int
    failed_tasks: int


class UpdateConfigRequest(BaseModel):
    """更新全局配置请求"""
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


# ==================== 浏览器管理 ====================

@router.get("/browsers")
async def list_browsers():
    """列出所有浏览器"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    status = browser_pool.get_status()
    return {
        "total": status["total_browsers"],
        "status_count": status["status_count"],
        "browsers": status["browsers"],
    }


@router.post("/browsers", response_model=BrowserResponse)
async def create_browser(request: CreateBrowserRequest):
    """创建新浏览器"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        browser_id = await browser_pool.create_browser(
            browser_id=request.browser_id,
            account_name=request.account_name,
            proxy=request.proxy,
            headless=request.headless,
            auto_start=request.auto_start,
            max_tabs=request.max_tabs,
        )

        browser = browser_pool.get_browser(browser_id)
        if browser is None:
            raise HTTPException(status_code=500, detail="Failed to create browser")

        return BrowserResponse(
            browser_id=browser.browser_id,
            account_name=browser.account_name,
            proxy=browser.proxy,
            status=browser.status.value,
            total_tasks=browser.total_tasks,
            failed_tasks=browser.failed_tasks,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/browsers/{browser_id}")
async def get_browser(browser_id: str):
    """获取浏览器详情"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    return browser.to_dict()


@router.put("/browsers/{browser_id}")
async def update_browser(browser_id: str, request: UpdateBrowserRequest):
    """更新浏览器配置"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    # 过滤 None 值
    updates = {k: v for k, v in request.model_dump().items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    try:
        browser = await browser_pool.update_browser(browser_id, updates)
        if browser is None:
            raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

        return browser.to_dict()

    except KeyError:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/browsers/{browser_id}")
async def delete_browser(browser_id: str):
    """删除浏览器"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        await browser_pool.remove_browser(browser_id)
        return {"message": f"Browser {browser_id} deleted"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/browsers/{browser_id}/start")
async def start_browser(browser_id: str):
    """启动浏览器"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        await browser_pool.start_browser(browser_id)
        browser = browser_pool.get_browser(browser_id)
        return {
            "message": f"Browser {browser_id} started",
            "status": browser.status.value if browser else "unknown",
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/browsers/{browser_id}/stop")
async def stop_browser(browser_id: str):
    """停止浏览器"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        await browser_pool.stop_browser(browser_id)
        browser = browser_pool.get_browser(browser_id)
        return {
            "message": f"Browser {browser_id} stopped",
            "status": browser.status.value if browser else "unknown",
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/browsers/{browser_id}/check-login")
async def check_browser_login(browser_id: str):
    """检查浏览器登录状态"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    try:
        result = await browser.check_login()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 全局配置 ====================

@router.get("/config")
async def get_config():
    """获取全局配置"""
    try:
        db = get_db()
        config = await db.get_global_config()
        return config.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/config")
async def update_config(request: UpdateConfigRequest):
    """更新全局配置"""
    # 过滤 None 值
    updates = {k: v for k, v in request.model_dump().items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    try:
        db = get_db()
        config = await db.update_global_config(updates)
        return config.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 任务管理 ====================

@router.get("/tasks")
async def list_tasks(
    browser_id: Optional[str] = Query(None, description="按浏览器 ID 筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    limit: int = Query(50, ge=1, le=200, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """获取任务列表"""
    try:
        db = get_db()
        tasks = await db.get_tasks(
            browser_id=browser_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "total": len(tasks),
            "limit": limit,
            "offset": offset,
            "tasks": [task.model_dump() for task in tasks],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/stats")
async def get_task_stats():
    """获取任务统计"""
    try:
        db = get_db()
        stats = await db.get_task_stats()
        return stats.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    try:
        db = get_db()
        task = await db.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        return task.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 日志管理 ====================

@router.get("/logs")
async def get_logs(
    browser_id: Optional[str] = Query(None, description="按浏览器 ID 筛选"),
    level: Optional[str] = Query(None, description="按日志级别筛选"),
    limit: int = Query(100, ge=1, le=500, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """获取事件日志"""
    try:
        db = get_db()
        logs = await db.get_logs(
            browser_id=browser_id,
            level=level,
            limit=limit,
            offset=offset,
        )
        return {
            "total": len(logs),
            "limit": limit,
            "offset": offset,
            "logs": [log.model_dump() for log in logs],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/logs")
async def clear_old_logs(days: int = Query(7, ge=1, le=90, description="清理多少天前的日志")):
    """清理旧日志"""
    try:
        db = get_db()
        await db.clear_old_logs(days)
        return {"message": f"Cleared logs older than {days} days"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 统计信息 ====================

@router.get("/stats")
async def get_stats():
    """获取统计信息"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        db = get_db()

        # 浏览器池状态
        pool_status = browser_pool.get_status()

        # 任务统计
        task_stats = await db.get_task_stats()

        return {
            "browsers": pool_status,
            "tasks": task_stats.model_dump(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 仪表盘 ====================

@router.get("/dashboard")
async def get_dashboard():
    """获取仪表盘数据"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        db = get_db()

        # 浏览器池状态
        pool_status = browser_pool.get_status()

        # 任务统计
        task_stats = await db.get_task_stats()

        # 最近日志
        recent_logs = await db.get_logs(limit=10)

        # 最近任务
        recent_tasks = await db.get_tasks(limit=10)

        return {
            "browsers": {
                "total": pool_status["total_browsers"],
                "status_count": pool_status["status_count"],
            },
            "tasks": task_stats.model_dump(),
            "recent_logs": [log.model_dump() for log in recent_logs],
            "recent_tasks": [task.model_dump() for task in recent_tasks],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
