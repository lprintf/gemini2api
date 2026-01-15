#!/bin/bash
set -e

# 清理残留的浏览器锁文件
rm -f /app/data/browser_data/*/Singleton* 2>/dev/null || true

# 启动 Weston RDP 后端（需要 ENABLE_DESKTOP=true 且证书存在）
if [ "${ENABLE_DESKTOP:-false}" = "true" ]; then
    if [ -f /etc/weston/tls.cert ] && [ -f /etc/weston/tls.key ]; then
        echo "Starting Weston RDP server..."
        weston --socket=wayland-0 --backend=rdp \
            --config=/app/weston.ini \
            --rdp-tls-cert=/etc/weston/tls.cert \
            --rdp-tls-key=/etc/weston/tls.key \
            --port=3500 \
            --width=${SCREEN_WIDTH:-1280} \
            --height=${SCREEN_HEIGHT:-720} &
        sleep 2
        echo "Weston started on port 3500"
    else
        echo "TLS certificates not found, Weston not started"
        echo "Mount certificates to /etc/weston for RDP support"
    fi
else
    echo "Desktop disabled (set ENABLE_DESKTOP=true to enable)"
fi

# 启动 API 服务
exec uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
