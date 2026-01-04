# Gemini2API Dockerfile
# 基于 Playwright 官方镜像 + uv

FROM mcr.microsoft.com/playwright/python:v1.57.0-noble-amd64

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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

# 工作目录
WORKDIR /app

# 复制依赖配置并安装
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# 创建数据目录
RUN mkdir -p /app/data /app/browser_data /etc/weston

# 复制启动脚本
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# 暴露端口
# 8000: API 服务端口
# 3500: RDP 端口（有头模式调试）
EXPOSE 8000 3500

# 启动脚本（同时启动 Weston 和 API）
CMD ["/app/entrypoint.sh"]
