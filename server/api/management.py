"""
管理 API

用于管理浏览器、配置、任务、日志等（需要身份认证）
"""

import asyncio
from io import BytesIO
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from server.auth import verify_admin
from server.db.database import get_db
from server.services.scheduler.pool import BrowserPool
from server.services.tasks.system import ReinitializeTask
from server.services.tasks import actions
from server.services.tasks.parser import CommandParser
from server.utils.logger import get_tab_logger, tab_log
import traceback

router = APIRouter(
    prefix="/api/admin",
    tags=["Management"],
    dependencies=[Depends(verify_admin)],  # 对整个路由器应用认证
)


# 全局变量（由 app.py 初始化）
browser_pool: Optional[BrowserPool] = None


class CreateBrowserRequest(BaseModel):
    """创建浏览器请求"""

    browser_id: Optional[int] = None  # 可选的浏览器 ID，不提供则自动分配
    account_name: Optional[str] = None  # 可选的账号名称，默认等于 ID
    proxy: Optional[str] = None
    auto_start: bool = True
    max_tabs: int = 3  # 最大标签页数量


class UpdateBrowserRequest(BaseModel):
    """更新浏览器请求"""

    account_name: Optional[str] = None
    proxy: Optional[str] = None
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


    # 只处理前端实际发送的字段
    updates = {}
    for k, v in request.model_dump(exclude_unset=True).items():
        # 对于 proxy 字段，None 或空字符串都表示删除代理
        if k == "proxy":
            updates[k] = None if (v is None or v == "") else v
        else:
            updates[k] = v

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    try:
        browser = await browser_pool.update_browser(browser_id, updates)
        if browser is None:
            raise HTTPException(
                status_code=404, detail=f"Browser {browser_id} not found"
            )

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


@router.post("/browsers/{browser_id}/launch")
async def launch_browser(browser_id: str):
    """启动浏览器"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        await browser_pool.launch_browser(browser_id)
        browser = browser_pool.get_browser(browser_id)
        return {
            "message": f"Browser {browser_id} launched",
            "status": browser.status.value if browser else "unknown",
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/browsers/{browser_id}/close")
async def close_browser(browser_id: str):
    """停止浏览器"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    try:
        await browser_pool.close_browser(browser_id)
        browser = browser_pool.get_browser(browser_id)
        return {
            "message": f"Browser {browser_id} closed",
            "status": browser.status.value if browser else "unknown",
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    updates = {k: v for k, v in request.model_dump(exclude_unset=True).items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    try:
        db = get_db()
        config = await db.update_global_config(updates)

        # 同步更新内存中的 browser_pool 限制
        if browser_pool:
            if "max_browsers" in updates:
                browser_pool.max_browsers = updates["max_browsers"]
                print(f"[Config] Updated browser_pool.max_browsers to {updates['max_browsers']}")
            if "min_browsers" in updates:
                browser_pool.min_browsers = updates["min_browsers"]
            if "default_rate_limit" in updates:
                browser_pool.browser_rate_limit = updates["default_rate_limit"]
            if "rate_window_seconds" in updates:
                browser_pool.browser_rate_window = updates["rate_window_seconds"]

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
        task_list = await db.get_tasks(
            browser_id=browser_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "total": len(task_list),
            "limit": limit,
            "offset": offset,
            "tasks": [task.model_dump() for task in task_list],
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
async def clear_old_logs(
    days: int = Query(7, ge=1, le=90, description="清理多少天前的日志")
):
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
        recent_tasks_list = await db.get_tasks(limit=10)

        return {
            "browsers": {
                "total": pool_status["total_browsers"],
                "status_count": pool_status["status_count"],
            },
            "tasks": task_stats.model_dump(),
            "recent_logs": [log.model_dump() for log in recent_logs],
            "recent_tasks": [task.model_dump() for task in recent_tasks_list],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 远程控制 ====================


class MouseInputRequest(BaseModel):
    """鼠标输入请求"""

    action: str  # "move", "click", "scroll"
    x: float  # 相对于图片的 x 坐标 (0-1)
    y: float  # 相对于图片的 y 坐标 (0-1)
    button: str = "left"  # "left", "right", "middle"
    scroll_delta: float = 0  # 滚动量


class KeyboardInputRequest(BaseModel):
    """键盘输入请求"""

    action: str  # "type", "press"
    text: Optional[str] = None  # 用于 type
    key: Optional[str] = None  # 用于 press


class NavigateRequest(BaseModel):
    """导航请求"""
    url: str
    wait_until: str = "load"  # "load", "domcontentloaded", "networkidle"


class SelectorActionRequest(BaseModel):
    """基于选择器的动作请求"""
    action: str  # "click", "input", "new_chat", "set_model"
    selector: Optional[str] = None
    selectors: Optional[List[str]] = None
    text: Optional[str] = None
    model: Optional[str] = "Fast"


class CommandExecuteRequest(BaseModel):
    """纯字符串命令请求"""
    cmd: str


# 存储最近的点击位置（用于在截图上绘制标记）
# 格式: {f"{browser_id}-{tab_id}": (x_pixel, y_pixel)}
_last_click: dict = {}


@router.get("/browsers/{browser_id}/tabs")
async def list_browser_tabs(browser_id: str):
    """获取浏览器的所有标签页"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    tabs_info = []
    for tab in browser.tabs:
        tab_info = tab.to_dict()
        tab_info["is_enabled"] = browser.is_enabled # Pass it here
        # 补充页面动态信息
        if tab.page:
            try:
                tab_info["url"] = tab.page.url
                tab_info["title"] = await tab.page.title()
            except Exception:
                tab_info["url"] = None
                tab_info["title"] = None
        tabs_info.append(tab_info)

    return {
        "browser_id": browser_id,
        "total_tabs": len(browser.tabs),
        "tabs": tabs_info,
    }


@router.get("/browsers/{browser_id}/tabs/{tab_id}/screenshot")
async def get_tab_screenshot(
    browser_id: str,
    tab_id: int,
    quality: int = Query(50, ge=1, le=100, description="WebP 质量 (1-100)"),
    full_page: bool = Query(False, description="是否截取整页"),
):
    """获取标签页截图 (WebP 格式)"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    # 查找指定的标签页
    tab = None
    for t in browser.tabs:
        if t.tab_id == tab_id:
            tab = t
            break

    if tab is None:
        raise HTTPException(
            status_code=404, detail=f"Tab {tab_id} not found in browser {browser_id}"
        )

    if tab.page is None:
        raise HTTPException(status_code=400, detail=f"Tab {tab_id} is not ready")

    try:
        # 截图到字节流
        screenshot_bytes = await tab.page.screenshot(
            type="png",  # Playwright 原生只支持 png/jpeg
            full_page=full_page,
        )

        # 转换为 PIL Image
        from PIL import Image, ImageDraw

        img = Image.open(BytesIO(screenshot_bytes))

        # 获取视口尺寸
        viewport_size = tab.page.viewport_size or {"width": 1280, "height": 900}

        # 如果有最近的点击位置，在图上画红点
        tab_key = f"{browser_id}-{tab_id}"
        if tab_key in _last_click:
            click_x, click_y = _last_click[tab_key]
            draw = ImageDraw.Draw(img)
            # 画一个红色圆点（半径8像素）
            r = 8
            draw.ellipse(
                [click_x - r, click_y - r, click_x + r, click_y + r],
                fill="red",
                outline="white",
                width=2,
            )
            # 画完后清除记录
            del _last_click[tab_key]

        webp_buffer = BytesIO()
        img.save(webp_buffer, format="WEBP", quality=quality)
        webp_bytes = webp_buffer.getvalue()

        return Response(
            content=webp_bytes,
            media_type="image/webp",
            headers={
                "X-Viewport-Width": str(viewport_size["width"]),
                "X-Viewport-Height": str(viewport_size["height"]),
                "Cache-Control": "no-cache, no-store, must-revalidate",
            },
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {str(e)}")


@router.post("/browsers/{browser_id}/tabs/{tab_id}/mouse")
async def send_mouse_input(browser_id: str, tab_id: int, request: MouseInputRequest):
    """发送鼠标输入到标签页"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    # 查找指定的标签页
    tab = None
    for t in browser.tabs:
        if t.tab_id == tab_id:
            tab = t
            break

    if tab is None:
        raise HTTPException(
            status_code=404, detail=f"Tab {tab_id} not found in browser {browser_id}"
        )

    if tab.page is None:
        raise HTTPException(status_code=400, detail=f"Tab {tab_id} is not ready")

    try:
        page = tab.page
        viewport_size = page.viewport_size or {"width": 1280, "height": 900}

        # 将相对坐标转换为实际像素坐标（整数）
        actual_x = int(request.x * viewport_size["width"])
        actual_y = int(request.y * viewport_size["height"])

        print(
            f"[Remote] Mouse {request.action}: ({actual_x}, {actual_y}) button={request.button}"
        )

        if request.action == "move":
            await page.mouse.move(actual_x, actual_y)
        elif request.action == "click":
            # 先移动到目标位置，再点击
            await page.mouse.move(actual_x, actual_y)
            await page.mouse.down(button=request.button)
            await page.mouse.up(button=request.button)
            # 记录点击位置，供下次截图时画点
            _last_click[f"{browser_id}-{tab_id}"] = (actual_x, actual_y)
        elif request.action == "scroll":
            await page.mouse.move(actual_x, actual_y)
            await page.mouse.wheel(0, int(request.scroll_delta))
        else:
            raise HTTPException(
                status_code=400, detail=f"Unknown action: {request.action}"
            )

        return {
            "success": True,
            "action": request.action,
            "x": actual_x,
            "y": actual_y,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Mouse input failed: {str(e)}")


@router.post("/browsers/{browser_id}/tabs/{tab_id}/keyboard")
async def send_keyboard_input(
    browser_id: str, tab_id: int, request: KeyboardInputRequest
):
    """发送键盘输入到标签页"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    # 查找指定的标签页
    tab = None
    for t in browser.tabs:
        if t.tab_id == tab_id:
            tab = t
            break

    if tab is None:
        raise HTTPException(
            status_code=404, detail=f"Tab {tab_id} not found in browser {browser_id}"
        )

    if tab.page is None:
        raise HTTPException(status_code=400, detail=f"Tab {tab_id} is not ready")

    try:
        page = tab.page

        if request.action == "type" and request.text:
            await page.keyboard.type(request.text)
        elif request.action == "press" and request.key:
            await page.keyboard.press(request.key)
        else:
            raise HTTPException(
                status_code=400, detail="Invalid keyboard action or missing parameters"
            )

        return {
            "success": True,
            "action": request.action,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Keyboard input failed: {str(e)}")


@router.post("/browsers/{browser_id}/tabs/{tab_id}/navigate")
async def navigate_tab(browser_id: str, tab_id: int, request: NavigateRequest):
    """导航标签页到指定 URL"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    # 查找指定的标签页
    tab = None
    for t in browser.tabs:
        if t.tab_id == tab_id:
            tab = t
            break

    if tab is None:
        raise HTTPException(
            status_code=404, detail=f"Tab {tab_id} not found in browser {browser_id}"
        )

    if tab.page is None:
        raise HTTPException(status_code=400, detail=f"Tab {tab_id} is not ready")

    try:
        page = tab.page

        # 导航到指定 URL
        await page.goto(request.url, wait_until=request.wait_until, timeout=30000)

        # 获取当前页面信息
        current_url = page.url
        title = await page.title()

        return {
            "success": True,
            "url": current_url,
            "title": title,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Navigation failed: {str(e)}")


@router.post("/browsers/{browser_id}/tabs/{tab_id}/reinitialize")
async def reinitialize_tab(browser_id: str, tab_id: int):
    """重新初始化标签页"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if browser is None:
        raise HTTPException(status_code=404, detail=f"Browser {browser_id} not found")

    # 查找指定的标签页
    tab = None
    for t in browser.tabs:
        if t.tab_id == tab_id:
            tab = t
            break

    if tab is None:
        raise HTTPException(
            status_code=404, detail=f"Tab {tab_id} not found in browser {browser_id}"
        )

    try:
        from server.services.tasks import actions
        success = await actions.reinitialize_page(tab.page, model=tab.model)
        
        # 更新状态
        from server.services.objects.exceptions import BrowserStatus
        tab.status = BrowserStatus.IDLE if success else BrowserStatus.ERROR
        tab.last_active_at = datetime.now()

        return {
            "success": success,
            "browser_id": browser_id,
            "tab_id": tab_id,
            "status": tab.status.value,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reinitialize failed: {str(e)}")


@router.get("/tabs")
async def list_all_tabs():
    """获取所有浏览器的所有标签页"""
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    all_tabs = []
    for browser in browser_pool.browsers.values():
        for tab in browser.tabs:
            tab_info = tab.to_dict()
            tab_info["is_enabled"] = browser.is_enabled
            # 尝试获取页面标题和 URL
            if tab.page:
                try:
                    tab_info["url"] = tab.page.url
                except Exception:
                    tab_info["url"] = None
            all_tabs.append(tab_info)

    # 按 browser_id, tab_id 排序
    all_tabs.sort(key=lambda x: (x["browser_id"], x["tab_id"]))

    # 统计各状态数量
    status_count = {}
    for tab in all_tabs:
        status = tab["status"]
        status_count[status] = status_count.get(status, 0) + 1

    return {
        "total": len(all_tabs),
        "status_count": status_count,
        "tabs": all_tabs,
    }


@router.post("/browsers/{browser_id}/tabs/{tab_id}/action")
async def execute_selector_action(browser_id: str, tab_id: int, request: SelectorActionRequest):
    """在指定的标签页上执行原子动作 (传统接口，仅做格式转换)"""
    # 直接构建命令字符串，所有别名由 CommandParser 统一处理
    action = request.action
    
    if action == "input":
        if request.selector:
            cmd = f'input "{request.text}" selector="{request.selector}"'
        else:
            cmd = f'input "{request.text}"'
    elif action == "click":
        if request.selector:
            cmd = f'click selector="{request.selector}"'
        else:
            cmd = "click"
    elif action == "set_model":
        cmd = f"model {request.model}"
    else:
        # 其他动作直接传递（如 new_chat, submit 等由 parser aliases 处理）
        if request.selector:
            cmd = f'{action} selector="{request.selector}"'
        else:
            cmd = action
        
    return await execute_raw_command(browser_id, tab_id, CommandExecuteRequest(cmd=cmd))


@router.post("/browsers/{browser_id}/tabs/{tab_id}/command")
async def execute_raw_command(browser_id: str, tab_id: int, request: CommandExecuteRequest):
    """解析并执行字符串指令 (全动态引擎)"""
    parsed = CommandParser.parse(request.cmd)
    if not parsed:
        return {"success": False, "error": f"Invalid command format: {request.cmd}"}
    
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    browser = browser_pool.get_browser(browser_id)
    if not browser:
        raise HTTPException(status_code=404, detail="Browser not found")

    tab = next((t for t in browser.tabs if t.tab_id == tab_id), None)
    if not tab or not tab.page:
        raise HTTPException(status_code=400, detail="Tab not ready")

    target_action = parsed["action"]
    args = parsed["args"]
    kwargs = parsed["kwargs"]
    
    # 挂载 per-tab logger 和账号名，确保调试输出和动作能获取上下文
    tab.page._logger = get_tab_logger(browser_id, tab_id)
    tab.page._account_name = browser.account_name
    
    success = False
    error = None

    try:
        tab_log(tab.page, f"[Command] Executing action '{target_action}' on Browser {browser_id} Tab {tab_id}")
        # 1. 动态查找 actions 模块
        func = getattr(actions, target_action, None)
        
        if func and callable(func):
            tab_log(tab.page, f"[Command] Calling actions.{target_action} with args={args} kwargs={kwargs}")
            # 自动注入 page 作为第一个参数
            res = func(tab.page, *args, **kwargs)
            if asyncio.iscoroutine(res):
                success = await res
            else:
                success = res
            tab_log(tab.page, f"[Command] execution success: {success}")
        
        # 2. 处理特殊内置指令
        elif target_action == "sleep":
            seconds = args[0] if args else 1
            tab_log(tab.page, f"[Command] Sleeping for {seconds}s")
            await asyncio.sleep(float(seconds))
            success = True
        
        elif target_action == "goto":
            if not args: raise ValueError("URL is required for goto")
            tab_log(tab.page, f"[Command] Navigating to {args[0]}")
            await tab.page.goto(args[0], wait_until="networkidle")
            success = True
        
        elif target_action in ("eval", "js"):
            # 执行任意 JavaScript
            if not args: raise ValueError("JS code is required for eval")
            js_code = args[0]
            tab_log(tab.page, f"[Command] JS result: {result}")
            return {"success": True, "result": result}
            
        else:
            success = False
            error = f"Action '{target_action}' not found in actions.py or built-ins"
            tab_log(tab.page, f"[Command] Error: {error}", "error")

    except Exception as e:
        success = False
        error = str(e)
        error_trace = traceback.format_exc()
        tab_log(tab.page, f"[Command] Exception occurred: {error}\n{error_trace}", "error")

    return {
        "success": success, 
        "error": error, 
        "executed": {
            "action": target_action,
            "args": args,
            "kwargs": kwargs
        }
    }
