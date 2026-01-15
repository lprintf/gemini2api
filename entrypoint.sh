#!/bin/bash
set -e

# 清理残留的浏览器锁文件
rm -f /app/data/browser_data/*/Singleton* 2>/dev/null || true

# 启动 API 服务
exec uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
