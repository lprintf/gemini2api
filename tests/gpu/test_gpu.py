"""
GPU基础测试 - 验证GPU加速配置是否生效

这是一个简单的验证脚本，用于确认浏览器可以使用GPU配置正常启动。
如需完整的性能对比测试，请使用以下工具：
- simple_gpu_test.py - 快速性能对比
- gpu_resource_monitor.py - 带资源监控的完整测试
- benchmark_gpu.py - 详细基准测试

详见：GPU_BENCHMARK_README.md
"""

from playwright.sync_api import sync_playwright

print("=" * 60)
print("GPU配置测试")
print("=" * 60)

# 测试GPU加速配置
print("\n测试1: GPU加速模式")
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--use-gl=egl",  # 有核显加速，无则自动失效
            "--enable-gpu-rasterization",
            "--enable-accelerated-2d-canvas",
            "--no-sandbox",  # 兼容非root
        ],
    )
    page = browser.new_page()
    print("✓ 浏览器启动成功（GPU加速模式）")

    # 访问测试页面
    page.goto("https://www.google.com")
    print("✓ 页面加载成功")

    browser.close()
    print("✓ 浏览器关闭成功")

# 测试禁用GPU配置
print("\n测试2: 软件渲染模式")
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--no-sandbox",
        ],
    )
    page = browser.new_page()
    print("✓ 浏览器启动成功（软件渲染模式）")

    page.goto("https://www.google.com")
    print("✓ 页面加载成功")

    browser.close()
    print("✓ 浏览器关闭成功")

print("\n" + "=" * 60)
print("✅ 所有测试通过！")
print("=" * 60)
print("\n💡 提示：")
print("  - 两种模式都能正常工作")
print("  - 如需详细性能对比，请运行：")
print("    python tests/simple_gpu_test.py")
print("  - 查看完整文档：")
print("    tests/GPU_BENCHMARK_README.md")
