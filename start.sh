#!/bin/bash
set -e

# Gemini2API Docker 启动脚本
# 用法:
#   ./start.sh           - 启动 API 服务（无头模式）
#   ./start.sh headed    - 启动有头模式服务（用于登录调试）
#   ./start.sh login     - 进入容器执行登录操作
#   ./start.sh stop      - 停止所有服务
#   ./start.sh logs      - 查看日志

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CERTS_DIR="./certs"
IMAGE_NAME="gemini2api"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 生成 TLS 证书（RDP 需要）
generate_certs() {
    if [ ! -f "${CERTS_DIR}/tls.key" ] || [ ! -f "${CERTS_DIR}/tls.cert" ]; then
        log_info "Generating TLS certificates for RDP..."
        mkdir -p "${CERTS_DIR}"

        openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
            -keyout "${CERTS_DIR}/tls.key" \
            -out "${CERTS_DIR}/tls.cert" \
            -subj "/C=US/O=Gemini2API/CN=localhost" 2>/dev/null

        chmod 600 "${CERTS_DIR}"/tls.*
        log_info "Certificates generated: ${CERTS_DIR}"
    fi
}

# 创建必要目录
init_dirs() {
    mkdir -p browser_data data certs
}

# 启动 API 服务
start_api() {
    log_info "Starting Gemini2API service..."
    docker compose up -d gemini2api

    log_info "Waiting for service to start..."
    sleep 5

    if docker compose ps gemini2api | grep -q "Up"; then
        log_info "Gemini2API started successfully!"
        echo ""
        echo "========================================"
        echo "  API Service: http://localhost:${API_PORT:-8000}"
        echo "  Admin Panel: http://localhost:${API_PORT:-8000}/admin"
        echo "  API Docs:    http://localhost:${API_PORT:-8000}/docs"
        echo "========================================"
        echo ""
        echo "Commands:"
        echo "  View logs:   docker compose logs -f gemini2api"
        echo "  Stop:        ./start.sh stop"
        echo "  Login:       ./start.sh login"
        echo ""
    else
        log_error "Failed to start service"
        docker compose logs gemini2api
        exit 1
    fi
}

# 启动有头模式（用于调试）
start_headed() {
    generate_certs

    log_info "Starting headed mode service..."
    docker compose --profile headed up -d gemini2api-headed

    sleep 3

    if docker compose ps gemini2api-headed | grep -q "Up"; then
        log_info "Headed mode started!"
        echo ""
        echo "========================================"
        echo "  RDP Connection: localhost:${RDP_PORT:-3500}"
        echo "========================================"
        echo ""
        echo "Connect via:"
        echo "  Windows: mstsc /v:localhost:${RDP_PORT:-3500}"
        echo "  macOS:   Microsoft Remote Desktop"
        echo "  Linux:   xfreerdp /v:localhost:${RDP_PORT:-3500} /cert:ignore"
        echo ""
        echo "Enter container: docker exec -it gemini2api-headed bash"
        echo ""
    else
        log_error "Failed to start headed mode"
        docker compose logs gemini2api-headed
        exit 1
    fi
}

# 执行登录操作
do_login() {
    local account_id="${1:-0}"

    # 确保有头模式服务运行
    if ! docker compose ps gemini2api-headed 2>/dev/null | grep -q "Up"; then
        log_info "Starting headed mode for login..."
        start_headed
    fi

    log_info "Starting login for account ${account_id}..."
    echo ""
    echo "Please connect to RDP (localhost:${RDP_PORT:-3500}) to see the browser"
    echo ""

    docker exec -it gemini2api-headed uv run python -m core.gemini_browser login "$account_id"
}

# 停止所有服务
stop_all() {
    log_info "Stopping all services..."
    docker compose --profile headed down
    log_info "All services stopped"
}

# 查看日志
show_logs() {
    docker compose logs -f "${1:-gemini2api}"
}

# 构建镜像
build_image() {
    log_info "Building Docker image..."
    docker compose build
    log_info "Build complete"
}

# 显示帮助
show_help() {
    echo "Gemini2API Docker Manager"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  (default)     Start API service (headless mode)"
    echo "  headed        Start headed mode service for debugging"
    echo "  login [id]    Start browser login (default account: 0)"
    echo "  stop          Stop all services"
    echo "  logs [name]   Show logs (default: gemini2api)"
    echo "  build         Build Docker image"
    echo "  help          Show this help"
    echo ""
    echo "Environment variables:"
    echo "  API_PORT      API service port (default: 8000)"
    echo "  RDP_PORT      RDP port for headed mode (default: 3500)"
    echo "  TZ            Timezone (default: Asia/Shanghai)"
    echo ""
    echo "Examples:"
    echo "  $0                      # Start API service"
    echo "  $0 headed               # Start with RDP for debugging"
    echo "  $0 login 0              # Login with account 0"
    echo "  API_PORT=9000 $0        # Start on port 9000"
}

# 主入口
main() {
    init_dirs

    case "${1:-}" in
        headed)
            start_headed
            ;;
        login)
            do_login "${2:-0}"
            ;;
        stop)
            stop_all
            ;;
        logs)
            show_logs "${2:-}"
            ;;
        build)
            build_image
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            start_api
            ;;
    esac
}

main "$@"
