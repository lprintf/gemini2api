#!/bin/bash
set -e

# Gemini2API Docker 启动脚本
# 用法:
#   ./start.sh           - 启动 API 服务
#   ./start.sh stop      - 停止服务
#   ./start.sh logs      - 查看日志
#   ./start.sh build     - 构建镜像

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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
        log_error "No docker compose command found"
        exit 1
    fi
}

DC=$(detect_compose)

# 创建必要目录
init_dirs() {
    # 从 .env 文件读取 DATA_DIR,否则使用默认值 ./data
    local data_dir="${DATA_DIR:-}"
    if [ -z "$data_dir" ] && [ -f ".env" ]; then
        data_dir=$(grep -E "^DATA_DIR=" .env 2>/dev/null | cut -d'=' -f2)
    fi
    data_dir="${data_dir:-./data}"

    # 创建必要的子目录
    mkdir -p "$data_dir/browser_data" "$data_dir/logs" "$data_dir/outputs" "$data_dir/uploads"
    chmod 777 "$data_dir/browser_data" 2>/dev/null || true
}

# 启动服务
start_api() {
    log_info "Starting Gemini2API services..."
    $DC up -d

    log_info "Waiting for service to start..."
    sleep 3

    if $DC ps gemini2api | grep -q "Up\|running"; then
        log_info "Gemini2API started successfully!"
        echo ""
        echo "========================================"
        echo "  Access: https://${COMPOSE_PROJECT_NAME:-gemini2api}.${DOMAIN}"
        echo "  Web Control: https://${COMPOSE_PROJECT_NAME:-gemini2api}.${DOMAIN}/remote"
        echo "========================================"
        echo ""
    else
        log_error "Failed to start service"
        $DC logs gemini2api
        exit 1
    fi
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
}

# 显示帮助
show_help() {
    echo "Gemini2API Docker Manager"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  (default)     Start all services"
    echo "  stop          Stop all services"
    echo "  logs          Show logs"
    echo "  build         Build Docker image"
    echo "  help          Show this help"
    echo ""
}

# 主入口
main() {
    init_dirs

    case "${1:-}" in
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
        login)
            log_warn "The 'login' command is deprecated. Please use the Web UI at /remote instead."
            ;;
        *)
            start_api
            ;;
    esac
}

main "$@"
