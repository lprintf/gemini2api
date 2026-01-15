"""
浏览器启动配置

集中管理 Chrome/Chromium 启动参数
"""

import os

# =============================================================================
# 基础参数（所有场景通用）
# =============================================================================

BASE_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--metrics-recording-only",
    "--no-first-run",
    "--disable-breakpad",
    "--no-default-browser-check",
    "--mute-audio",
]

# =============================================================================
# 高并发优化参数
# =============================================================================

# 禁用不必要的功能（减少 CPU 占用）
PERFORMANCE_ARGS = [
    "--force-device-scale-factor=0.5",  # 缩放因子设为 0.5，减少渲染像素量，节省 GPU/CPU
    # "--disable-hang-monitor",
    # "--disable-ipc-flooding-protection",
    # "--disable-client-side-phishing-detection",
    # "--disable-component-update",
    # "--disable-domain-reliability",
    # "--disable-features=TranslateUI,BlinkGenPropertyTrees,IsolateOrigins,site-per-process",
    # "--disable-popup-blocking",
    # "--disable-prompt-on-repost",
    # "--disable-default-apps",
    # "--memory-pressure-off",
    # "--max-gum-fps=1",
    # "--disable-partial-raster",
    # "--disable-skia-runtime-opts",
    # # 新增：禁用高开销渲染元素
    # "--disable-images",  # 禁用图片加载（无截图/视觉验证需求时优先开启，CPU 节省 20%-30%）
    # "--disable-css-animation",  # 禁用 CSS 动画/过渡/关键帧，避免持续渲染刷新
    # "--disable-html5-video",  # 禁用 HTML5 视频/音频播放，减少解码开销
    # "--disable-webgl",  # 禁用 WebGL 3D 绘制，避免无用的 3D 计算
    # "--disable-canvas-aa",  # 禁用 Canvas 抗锯齿，减少 Canvas 渲染计算量
    # "--disable-font-subpixel-positioning",  # 禁用字体亚像素定位，简化文字渲染
    # # 页面行为优化
    # "--disable-smooth-scrolling",  # 禁用平滑滚动，避免滚动时的连续重绘
    # "--disable-auto-reload",  # 禁用页面自动刷新，避免重复渲染
    # "--disable-popup-blocking",  # 禁用弹窗拦截（避免浏览器后台持续检测弹窗，减少 CPU 空
    # # 渲染优化
    # "--low-res-tiling",  # 启用低分辨率分块渲染，简化大图/长页面渲染
    # "--force-device-scale-factor=1",  # 固定设备缩放比例为 1，避免缩放适配的渲染计算
]

# =============================================================================
# Headless 模式参数
# =============================================================================

HEADLESS_ARGS = [
    "--headless=new",
]

# =============================================================================
# Wayland 环境参数
# =============================================================================

WAYLAND_ARGS = [
    "--ozone-platform=wayland",
    "--enable-features=UseOzonePlatform",
]


def get_launch_args(headless: bool = True, proxy: str = None) -> list[str]:
    """
    获取浏览器启动参数

    Args:
        headless: 是否使用无头模式
        proxy: 代理服务器地址

    Returns:
        启动参数列表
    """
    args = BASE_ARGS.copy()
    args.extend(PERFORMANCE_ARGS)

    if headless:
        args.extend(HEADLESS_ARGS)
    else:
        # GUI 模式下检查 Wayland 环境
        if os.environ.get("WAYLAND_DISPLAY"):
            args.extend(WAYLAND_ARGS)

    if proxy:
        args.append(f"--proxy-server={proxy}")

    return args


# =============================================================================
# 默认配置
# =============================================================================

DEFAULT_VIEWPORT = {"width": 384, "height": 512}  # 原 768x1024 减半，配合 0.5 缩放因子节省资源
DEFAULT_TIMEOUT = 60000  # 60 秒
DEFAULT_PERMISSIONS = ["clipboard-read", "clipboard-write"]
