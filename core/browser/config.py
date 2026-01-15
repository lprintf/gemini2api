"""
浏览器启动配置（无头模式专用）

集中管理 Chrome/Chromium 启动参数
"""

# =============================================================================
# 基础参数
# =============================================================================

BASE_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--headless=new",
]


def get_launch_args(proxy: str = None) -> list[str]:
    """
    获取浏览器启动参数

    Args:
        proxy: 代理服务器地址

    Returns:
        启动参数列表
    """
    args = BASE_ARGS.copy()

    if proxy:
        args.append(f"--proxy-server={proxy}")

    return args


# =============================================================================
# 默认配置
# =============================================================================

DEFAULT_VIEWPORT = {"width": 512, "height": 1024}
DEFAULT_TIMEOUT = 60000  # 60 秒
DEFAULT_PERMISSIONS = ["clipboard-read", "clipboard-write"]
