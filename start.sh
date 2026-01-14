#!/bin/bash
set -e

# Gemini2API Docker 启动脚本
# 用法:
#   ./start.sh           - 启动 API 服务
#   ./start.sh login     - 启动 Weston 并执行登录操作
#   ./start.sh stop      - 停止服务
#   ./start.sh logs      - 查看日志

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CERTS_DIR="./certs"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 自动检测 docker compose 命令
detect_compose() {
    if docker compose version &>/dev/null; then
        echo "docker compose"
    elif docker-compose version &>/dev/null; then
        echo "docker-compose"
    else
        log_error "No docker compose command found (dc, docker compose, docker-compose)"
        exit 1
    fi
}

DC=$(detect_compose)

# 获取容器名（基于 COMPOSE_PROJECT_NAME）
get_container_name() {
    # 优先从 .env 文件读取，否则使用目录名作为默认值
    local project_name="${COMPOSE_PROJECT_NAME:-}"
    if [ -z "$project_name" ] && [ -f ".env" ]; then
        project_name=$(grep -E "^COMPOSE_PROJECT_NAME=" .env 2>/dev/null | cut -d'=' -f2)
    fi
    # 如果仍为空，使用当前目录名（docker compose 默认行为）
    if [ -z "$project_name" ]; then
        project_name=$(basename "$SCRIPT_DIR")
    fi
    echo "${project_name}-gemini2api-1"
}

CONTAINER_NAME=$(get_container_name)

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
    # 从 .env 文件读取 DATA_DIR,否则使用默认值 ./data
    local data_dir="${DATA_DIR:-}"
    if [ -z "$data_dir" ] && [ -f ".env" ]; then
        data_dir=$(grep -E "^DATA_DIR=" .env 2>/dev/null | cut -d'=' -f2)
    fi
    # 如果仍为空,使用默认值
    data_dir="${data_dir:-./data}"

    # 创建必要的子目录
    mkdir -p "$data_dir/browser_data" "$data_dir/logs" "$data_dir/outputs" "$data_dir/uploads" certs
    # 确保有写入权限
    chmod 777 "$data_dir" "$data_dir/browser_data" 2>/dev/null || true
}

# 启动服务
start_api() {
    generate_certs

    log_info "Starting Gemini2API services..."
    $DC up -d

    log_info "Waiting for service to start..."
    sleep 5

    if $DC ps gemini2api | grep -q "Up\|running"; then
        log_info "Gemini2API started successfully!"
        echo ""
        echo "========================================"
        echo "  Access: https://${COMPOSE_PROJECT_NAME:-gemini2api}.${DOMAIN}"
        echo "========================================"
        echo ""
        echo "Commands:"
        echo "  View logs:   ./start.sh logs"
        echo "  Stop:        ./start.sh stop"
        echo "  Login:       ./start.sh login"
        echo ""
    else
        log_error "Failed to start service"
        $DC logs gemini2api
        exit 1
    fi
}

# 执行登录操作（在同一容器内按需启动 Weston）
do_login() {
    local account_id="${1:-0}"

    generate_certs

    # 确保容器运行
    if ! $DC ps gemini2api 2>/dev/null | grep -q "Up\|running"; then
        log_info "Starting container..."
        $DC up -d gemini2api
        sleep 3
    fi

    # 在容器内按需启动 Weston（使用 docker exec -d 避免僵尸进程）
    log_info "Starting Weston RDP server..."
    if docker exec "$CONTAINER_NAME" pgrep -x weston > /dev/null 2>&1; then
        log_info "Weston already running"
    else
        docker exec -d "$CONTAINER_NAME" weston --socket=wayland-0 --backend=rdp \
            --rdp-tls-cert=/etc/weston/tls.cert \
            --rdp-tls-key=/etc/weston/tls.key \
            --port=3500 --width=${SCREEN_WIDTH:-1920} --height=${SCREEN_HEIGHT:-1080}
        sleep 2
        log_info "Weston started (${SCREEN_WIDTH:-1920}x${SCREEN_HEIGHT:-1080})"
    fi

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

    log_info "Starting login for account ${account_id}..."
    echo "Please connect to RDP to see the browser"
    echo ""

    # 运行登录脚本
    docker exec -it "$CONTAINER_NAME" uv run python -m core.gemini_browser login "$account_id"
}

# 停止所有服务
stop_all() {
    log_info "Stopping all services..."
    $DC down
    log_info "All services stopped"
}

# 查看日志
show_logs() {
    $DC logs -f
}

# 构建镜像
build_image() {
    log_info "Building Docker image..."
    $DC build
    log_info "Build complete"
}

# 显示帮助
show_help() {
    echo "Gemini2API Docker Manager"
    echo ""
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  (default)     Start all services"
    echo "  login [id]    Start Weston + browser login (default account: 0)"
    echo "  stop          Stop all services"
    echo "  logs          Show logs"
    echo "  build         Build Docker image"
    echo "  help          Show this help"
    echo ""
    echo "Environment variables:"
    echo "  RDP_PORT      RDP port for login (default: 3500)"
    echo "  TZ            Timezone (default: Asia/Shanghai)"
    echo ""
    echo "Examples:"
    echo "  $0                      # Start all services"
    echo "  $0 login 0              # Login with account 0"
}

# 主入口
main() {
    init_dirs

    case "${1:-}" in
        login)
            do_login "${2:-0}"
            ;;
        stop)
            stop_all
            ;;
        logs)
            show_logs
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
