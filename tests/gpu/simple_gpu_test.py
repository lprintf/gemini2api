"""
简化版GPU性能测试 - 专门用于快速对比测试

使用方法：
    python simple_gpu_test.py
"""

import asyncio
import time

from playwright.async_api import async_playwright


async def test_browser_config(
    name: str, args: list, test_url: str = "https://www.google.com"
):
    """测试特定浏览器配置"""
    print(f"\n{'='*50}")
    print(f"测试配置: {name}")
    print(f"{'='*50}")
    print(f"启动参数: {args}")

    start_time = time.time()

    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=True, args=args)

        launch_time = time.time() - start_time
        print(f"✓ 浏览器启动耗时: {launch_time:.2f}s")

        # 创建页面并访问URL
        page = await browser.new_page()

        nav_start = time.time()
        await page.goto(test_url, wait_until="networkidle")
        nav_time = time.time() - nav_start
        print(f"✓ 页面加载耗时: {nav_time:.2f}s")

        # 执行一些渲染测试
        render_start = time.time()
        await page.evaluate(
            """
            () => {
                // 创建一些需要GPU加速的元素
                const container = document.createElement('div');
                container.style.cssText = 'position: absolute; top: 0; left: 0;';

                for (let i = 0; i < 500; i++) {
                    const div = document.createElement('div');
                    div.style.cssText = `
                        width: 50px;
                        height: 50px;
                        background: linear-gradient(45deg, #ff0000, #0000ff);
                        transform: rotate(${i}deg) translateX(${i}px);
                        margin: 2px;
                        display: inline-block;
                        transition: all 0.3s;
                    `;
                    container.appendChild(div);
                }

                document.body.appendChild(container);

                // 强制重排和重绘
                container.offsetHeight;
            }
        """
        )

        await asyncio.sleep(1)  # 等待渲染完成
        render_time = time.time() - render_start
        print(f"✓ 渲染测试耗时: {render_time:.2f}s")

        # 获取性能指标
        metrics = await page.evaluate(
            """
            () => {
                const timing = performance.timing;
                return {
                    domContentLoaded: timing.domContentLoadedEventEnd - timing.navigationStart,
                    loadComplete: timing.loadEventEnd - timing.navigationStart,
                    domInteractive: timing.domInteractive - timing.navigationStart,
                };
            }
        """
        )

        print(f"✓ DOM加载: {metrics['domContentLoaded']}ms")
        print(f"✓ 页面完成: {metrics['loadComplete']}ms")

        await browser.close()

        total_time = time.time() - start_time
        print(f"✓ 总耗时: {total_time:.2f}s")

        return {
            "name": name,
            "launch_time": launch_time,
            "navigation_time": nav_time,
            "render_time": render_time,
            "total_time": total_time,
            "metrics": metrics,
        }


async def main():
    """运行对比测试"""
    print("\n🚀 开始GPU性能对比测试")

    # 测试URL（可以改成你实际要测试的URL）
    test_url = "https://www.google.com"

    # GPU加速配置
    gpu_args = [
        "--use-gl=egl",
        "--enable-gpu-rasterization",
        "--enable-accelerated-2d-canvas",
        "--no-sandbox",
    ]

    # 禁用GPU配置
    no_gpu_args = [
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-dev-shm-usage",
        "--no-sandbox",
    ]

    # 运行测试
    results = []

    # 测试GPU模式
    result_gpu = await test_browser_config("GPU加速模式", gpu_args, test_url)
    results.append(result_gpu)

    await asyncio.sleep(2)  # 等待系统恢复

    # 测试非GPU模式
    result_no_gpu = await test_browser_config("软件渲染模式", no_gpu_args, test_url)
    results.append(result_no_gpu)

    # 打印对比结果
    print(f"\n{'='*50}")
    print("📊 性能对比总结")
    print(f"{'='*50}")

    gpu_total = result_gpu["total_time"]
    no_gpu_total = result_no_gpu["total_time"]
    improvement = ((no_gpu_total - gpu_total) / no_gpu_total) * 100

    print(f"\n⏱️  总耗时对比:")
    print(f"  GPU加速: {gpu_total:.2f}s")
    print(f"  软件渲染: {no_gpu_total:.2f}s")
    print(f"  性能提升: {improvement:+.1f}%")

    print(f"\n⏱️  导航时间对比:")
    print(f"  GPU加速: {result_gpu['navigation_time']:.2f}s")
    print(f"  软件渲染: {result_no_gpu['navigation_time']:.2f}s")
    nav_improvement = (
        (result_no_gpu["navigation_time"] - result_gpu["navigation_time"])
        / result_no_gpu["navigation_time"]
    ) * 100
    print(f"  性能提升: {nav_improvement:+.1f}%")

    print(f"\n⏱️  渲染时间对比:")
    print(f"  GPU加速: {result_gpu['render_time']:.2f}s")
    print(f"  软件渲染: {result_no_gpu['render_time']:.2f}s")
    render_improvement = (
        (result_no_gpu["render_time"] - result_gpu["render_time"])
        / result_no_gpu["render_time"]
    ) * 100
    print(f"  性能提升: {render_improvement:+.1f}%")

    print("\n💡 建议:")
    if improvement > 5:
        print("  ✅ GPU加速带来明显性能提升，建议启用")
    elif improvement < -5:
        print("  ⚠️  GPU加速反而降低性能，建议禁用（可能无GPU硬件）")
    else:
        print("  ℹ️  性能差异不明显，根据实际情况选择")


if __name__ == "__main__":
    asyncio.run(main())
