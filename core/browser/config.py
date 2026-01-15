"""
浏览器启动配置（无头模式专用）

集中管理 Chrome/Chromium 启动参数
"""

# =============================================================================
# 基础参数
# =============================================================================

BASE_ARGS = [
    "--no-sandbox",
    # "--disable-setuid-sandbox",
    "--headless=new",

    # # 基础参数
    # "--disable-gpu",
    # "--disable-software-rasterizer",
    # "--disable-extensions",
    # "--disable-background-networking",
    # "--disable-sync",
    # "--metrics-recording-only",
    # "--no-first-run",
    # "--disable-breakpad",
    # "--no-default-browser-check",
    # "--mute-audio",
    # # 禁用不必要的功能（减少 CPU 占用）
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

DEFAULT_VIEWPORT = {"width": 820, "height": 1180} # 模拟手机浏览器尺寸
DEFAULT_TIMEOUT = 60000  # 60 秒
DEFAULT_PERMISSIONS = ["clipboard-read", "clipboard-write"]
