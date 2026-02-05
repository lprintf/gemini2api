"""
FastAPI 应用主入口
"""

from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from contextlib import asynccontextmanager
import uvicorn

from server.db.database import init_db, close_db, get_db
from server.config import init_config_from_db, init_config_sync, get_config
from server.services.scheduler.pool import BrowserPool
from server.services.scheduler.coordinator import TaskCoordinator
from server.api import openai_compatible, management, gemini_compatible
from server.auth import verify_admin


# 全局变量
browser_pool: BrowserPool | None = None
task_coordinator: TaskCoordinator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global browser_pool
    global task_coordinator

    # 启动时初始化
    print("Starting Gemini Image Edit API Server...")

    # 初始化数据库
    print("Initializing database...")
    await init_db()
    db = get_db()
    await db.add_log("INFO", "Server starting")

    # 从数据库加载配置
    print("Loading configuration from database...")
    config = await init_config_from_db()
    print(f"Config loaded: host={config.server.host}, port={config.server.port}")

    # 初始化浏览器池
    browser_pool = BrowserPool(
        min_browsers=config.browser_pool.min_browsers,
        max_browsers=config.browser_pool.max_browsers,
        browser_rate_limit=config.rate_limit.default_limit,
        browser_rate_window=config.rate_limit.window_seconds,
    )
    print(f"Browser pool initialized (max: {config.browser_pool.max_browsers}, rate_limit: {config.rate_limit.default_limit}/{config.rate_limit.window_seconds}s per browser)")

    # 从数据库加载已保存的浏览器配置
    print("Loading browsers from database...")
    await browser_pool.load_from_db()

    # 初始化任务协调者
    task_coordinator = TaskCoordinator(browser_pool)

    # 将全局变量注入到 API 模块
    openai_compatible.browser_pool = browser_pool
    openai_compatible.task_coordinator = task_coordinator
    management.browser_pool = browser_pool
    gemini_compatible.browser_pool = browser_pool
    gemini_compatible.task_coordinator = task_coordinator

    await db.add_log("INFO", "Server started successfully")
    print("Server started successfully!")

    yield

    # 关闭时清理
    print("\nShutting down server...")
    try:
        db = get_db()
        await db.add_log("INFO", "Server shutting down")
    except Exception:
        pass

    if browser_pool:
        await browser_pool.shutdown()

    # 关闭数据库连接
    await close_db()
    print("Server stopped")


# 初始化默认配置（用于 CORS 等中间件，在数据库初始化之前）
init_config_sync()


# 创建 FastAPI 应用
app = FastAPI(
    title="Gemini Image Edit API",
    description="OpenAI-compatible image editing API powered by Google Gemini",
    version="2.1.0",
    lifespan=lifespan,
)


# CORS 中间件
try:
    config = get_config()
    cors_origins = config.security.cors_origins
except RuntimeError:
    cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 注册路由
app.include_router(openai_compatible.router)
app.include_router(management.router)
app.include_router(gemini_compatible.router)


# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(username: str = Depends(verify_admin)):
    """管理页面（需要身份认证）"""
    admin_html = STATIC_DIR / "admin.html"
    if admin_html.exists():
        return FileResponse(admin_html)
    return HTMLResponse("<h1>Admin page not found</h1>", status_code=404)


@app.get("/remote", response_class=HTMLResponse)
async def remote_page(username: str = Depends(verify_admin)):
    """远程控制页面（需要身份认证）"""
    remote_html = STATIC_DIR / "remote.html"
    if remote_html.exists():
        return FileResponse(remote_html)
    return HTMLResponse("<h1>Remote control page not found</h1>", status_code=404)


@app.get("/", response_class=HTMLResponse)
async def root():
    """首页"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gemini Image Edit API</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                border-bottom: 3px solid #667eea;
                padding-bottom: 10px;
            }
            .info {
                background: #e8eaf6;
                padding: 15px;
                border-radius: 5px;
                margin: 20px 0;
            }
            a {
                color: #667eea;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            .endpoint {
                background: #f5f5f5;
                padding: 10px;
                margin: 10px 0;
                border-left: 4px solid #667eea;
                font-family: monospace;
            }
            .btn {
                display: inline-block;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                margin-top: 20px;
                font-weight: 600;
            }
            .btn:hover {
                text-decoration: none;
                opacity: 0.9;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Gemini Image Edit API</h1>
            <p>OpenAI-compatible image editing API powered by Google Gemini</p>
 
            <div class="info">
                <strong>Status:</strong> Running<br>
                <strong>API Docs:</strong> <a href="/docs">/docs</a><br>
                <strong>Alternative Docs:</strong> <a href="/redoc">/redoc</a><br>
                <strong>Admin Panel:</strong> <a href="/admin">/admin</a>
            </div>
 
            <a href="/admin" class="btn">Open Admin Panel</a>
 
            <h2>API Endpoints</h2>
 
            <h3>Gemini Compatible API</h3>
            <div class="endpoint">POST /v1beta/models/{model_id}:generateContent</div>
            <div class="endpoint">GET /v1beta/models</div>
            <div class="endpoint">GET /v1beta/models/{model_id}</div>
 
            <h3>OpenAI Compatible API</h3>
            <div class="endpoint">POST /v1/images/edits</div>
            <div class="endpoint">GET /v1/images/tasks/{task_id}</div>
            <div class="endpoint">GET /v1/models</div>
 
            <h3>Management API</h3>
            <div class="endpoint">GET /api/admin/browsers</div>
            <div class="endpoint">POST /api/admin/browsers</div>
            <div class="endpoint">PUT /api/admin/browsers/{browser_id}</div>
            <div class="endpoint">DELETE /api/admin/browsers/{browser_id}</div>
            <div class="endpoint">POST /api/admin/browsers/{browser_id}/start</div>
            <div class="endpoint">POST /api/admin/browsers/{browser_id}/stop</div>
            <div class="endpoint">GET /api/admin/browsers/{browser_id}/check-login</div>
            <div class="endpoint">GET /api/admin/config</div>
            <div class="endpoint">PUT /api/admin/config</div>
            <div class="endpoint">GET /api/admin/tasks</div>
            <div class="endpoint">GET /api/admin/tasks/stats</div>
            <div class="endpoint">GET /api/admin/logs</div>
            <div class="endpoint">GET /api/admin/dashboard</div>
 
            <h2>Authentication</h2>
            <p>API requests accept an optional API key in the <code>Authorization</code> header:</p>
            <div class="endpoint">Authorization: Bearer sk-your-api-key</div>
 
            <h2>Documentation</h2>
            <p>Visit <a href="/docs">/docs</a> for interactive API documentation.</p>
        </div>
    </body>
    </html>
    """
 
 
@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "browsers": browser_pool.get_status() if browser_pool else None,
    }
 
 
if __name__ == "__main__":
    # 开发模式运行
    try:
        config = get_config()
        host = config.server.host
        port = config.server.port
    except RuntimeError:
        host = "0.0.0.0"
        port = 8000
 
    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=True,
    )
