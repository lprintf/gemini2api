# Gemini2API Dockerfile
# 基于 Playwright 官方镜像，支持有头模式浏览器自动化

FROM mcr.microsoft.com/playwright/python:v1.57.0-noble-amd64

# 安装 Wayland 核心组件（用于有头模式 RDP 连接）
RUN apt-get update && apt-get install -y --no-install-recommends \
    weston \
    xwayland \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Wayland 环境变量
ENV XDG_RUNTIME_DIR=/tmp \
    WAYLAND_DISPLAY=wayland-0 \
    SCREEN_WIDTH=1920 \
    SCREEN_HEIGHT=1080

# 安装 uv（Python 包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 工作目录
WORKDIR /app

# 复制项目文件
COPY pyproject.toml ./
COPY main.py ./
COPY config/ ./config/
COPY core/ ./core/
COPY server/ ./server/
COPY tests/ ./tests/

# 安装 Python 依赖
RUN uv sync

# 创建数据目录
RUN mkdir -p /app/data /app/browser_data /etc/weston

# 暴露端口
# 8000: API 服务端口
# 3500: RDP 端口（有头模式调试）
EXPOSE 8000 3500

# 默认启动 API 服务
CMD ["uv", "run", "python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
