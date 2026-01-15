# Gemini2API Dockerfile（无头模式）
# 基于 Playwright 官方镜像 + uv

FROM mcr.microsoft.com/playwright/python:v1.57.0-noble-amd64

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

RUN mkdir -p /app/data /app/browser_data

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
