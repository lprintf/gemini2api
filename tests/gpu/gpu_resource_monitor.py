"""
带系统资源监控的GPU性能测试

需要安装: pip install psutil

使用方法：
    python gpu_resource_monitor.py
"""

import asyncio
import os
import signal
import time
from typing import Dict, List, Optional

import psutil
from playwright.async_api import async_playwright


class ProcessMonitor:
    """进程资源监控器"""

    def __init__(self):
        self.monitoring = False
        self.samples: List[Dict] = []
        self.monitor_task = None

    async def start_monitoring(self, process_name: str = "chromium"):
        """开始监控指定进程"""
        self.monitoring = True
        self.samples = []
        self.monitor_task = asyncio.create_task(self._monitor_loop(process_name))

    async def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        if self.monitor_task:
            await self.monitor_task

    async def _monitor_loop(self, process_name: str):
        """监控循环"""
        while self.monitoring:
            try:
                # 找到所有匹配的进程
                chrome_processes = []
                for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                    try:
                        if process_name.lower() in proc.info["name"].lower():
                            chrome_processes.append(proc)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

                if chrome_processes:
                    # 计算总资源使用
                    total_cpu = 0
                    total_memory = 0

                    for proc in chrome_processes:
                        try:
                            cpu = proc.cpu_percent(interval=0.1)
                            mem = proc.memory_info().rss
                            total_cpu += cpu
                            total_memory += mem
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue

                    sample = {
                        "timestamp": time.time(),
                        "cpu_percent": total_cpu,
                        "memory_mb": total_memory / 1024 / 1024,
                        "process_count": len(chrome_processes),
                    }
                    self.samples.append(sample)

            except Exception as e:
                print(f"监控错误: {e}")

            await asyncio.sleep(0.5)

    def get_summary(self) -> Optional[Dict]:
        """获取监控统计摘要"""
        if not self.samples:
            return None

        cpu_values = [s["cpu_percent"] for s in self.samples]
        mem_values = [s["memory_mb"] for s in self.samples]

        return {
            "cpu": {
                "avg": sum(cpu_values) / len(cpu_values),
                "max": max(cpu_values),
                "min": min(cpu_values),
            },
            "memory": {
                "avg": sum(mem_values) / len(mem_values),
                "max": max(mem_values),
                "min": min(mem_values),
            },
            "sample_count": len(self.samples),
        }


async def run_test_with_monitoring(config_name: str, browser_args: List[str], test_url: str):
    """运行带监控的浏览器测试"""
    print(f"\n{'='*60}")
    print(f"🔬 测试配置: {config_name}")
    print(f"{'='*60}")

    monitor = ProcessMonitor()

    async with async_playwright() as p:
        # 启动浏览器
        print("启动浏览器...")
        start_time = time.time()

        browser = await p.chromium.launch(headless=True, args=browser_args)
        context = await browser.new_context()
        page = await context.new_page()

        launch_time = time.time() - start_time
        print(f"✓ 启动耗时: {launch_time:.2f}s")

        # 开始监控
        await monitor.start_monitoring("chromium")

        # 导航到页面
        print(f"导航到: {test_url}")
        nav_start = time.time()
        await page.goto(test_url, wait_until="networkidle", timeout=30000)
        nav_time = time.time() - nav_start
        print(f"✓ 导航耗时: {nav_time:.2f}s")

        # 执行渲染测试
        print("执行渲染测试...")
        render_start = time.time()

        await page.evaluate("""
            () => {
                // 创建大量元素测试GPU渲染
                const container = document.createElement('div');
                container.id = 'test-container';
                container.style.cssText = 'position: relative; width: 100%; height: 100%;';

                // 创建渐变背景元素
                for (let i = 0; i < 200; i++) {
                    const div = document.createElement('div');
                    div.style.cssText = `
                        position: absolute;
                        width: 100px;
                        height: 100px;
                        background: linear-gradient(${i * 2}deg,
                            rgba(255, 0, 0, 0.5),
                            rgba(0, 0, 255, 0.5));
                        transform: rotate(${i * 3}deg) translate(${i % 10 * 50}px, ${Math.floor(i / 10) * 50}px);
                        border-radius: 50%;
                        box-shadow: 0 0 20px rgba(0,0,0,0.3);
                    `;
                    container.appendChild(div);
                }

                document.body.appendChild(container);

                // 触发动画
                setTimeout(() => {
                    const elements = container.children;
                    for (let i = 0; i < elements.length; i++) {
                        elements[i].style.transition = 'transform 1s ease-in-out';
                        elements[i].style.transform = `rotate(${360 + i * 3}deg) translate(${i % 10 * 50}px, ${Math.floor(i / 10) * 50}px) scale(1.2)`;
                    }
                }, 100);
            }
        """)

        # 等待动画和渲染完成
        await asyncio.sleep(3)

        render_time = time.time() - render_start
        print(f"✓ 渲染测试耗时: {render_time:.2f}s")

        # 获取性能指标
        perf_metrics = await page.evaluate("""
            () => {
                const timing = performance.timing;
                const paint = performance.getEntriesByType('paint');
                return {
                    domContentLoaded: timing.domContentLoadedEventEnd - timing.navigationStart,
                    loadComplete: timing.loadEventEnd - timing.navigationStart,
                    domInteractive: timing.domInteractive - timing.navigationStart,
                    firstPaint: paint.find(p => p.name === 'first-paint')?.startTime || 0,
                    firstContentfulPaint: paint.find(p => p.name === 'first-contentful-paint')?.startTime || 0,
                };
            }
        """)

        print(f"✓ DOM内容加载: {perf_metrics['domContentLoaded']}ms")
        print(f"✓ 页面加载完成: {perf_metrics['loadComplete']}ms")

        # 再等待一会儿收集更多资源数据
        await asyncio.sleep(2)

        # 停止监控
        await monitor.stop_monitoring()

        # 关闭浏览器
        await browser.close()

        # 获取监控摘要
        resource_summary = monitor.get_summary()

        total_time = time.time() - start_time

        result = {
            "config": config_name,
            "times": {
                "launch": launch_time,
                "navigation": nav_time,
                "render": render_time,
                "total": total_time,
            },
            "performance_metrics": perf_metrics,
            "resources": resource_summary,
        }

        # 打印资源使用摘要
        if resource_summary:
            print(f"\n📊 资源使用:")
            print(f"  CPU平均: {resource_summary['cpu']['avg']:.1f}%")
            print(f"  CPU峰值: {resource_summary['cpu']['max']:.1f}%")
            print(f"  内存平均: {resource_summary['memory']['avg']:.1f}MB")
            print(f"  内存峰值: {resource_summary['memory']['max']:.1f}MB")
            print(f"  采样次数: {resource_summary['sample_count']}")

        print(f"✓ 总耗时: {total_time:.2f}s")

        return result


async def main():
    """主函数"""
    print("\n" + "="*60)
    print("🚀 GPU性能与资源对比测试")
    print("="*60)

    test_url = "https://www.google.com"

    # GPU加速配置
    gpu_args = [
        "--use-gl=egl",
        "--enable-gpu-rasterization",
        "--enable-accelerated-2d-canvas",
        "--enable-accelerated-video-decode",
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
    print(f"\n测试URL: {test_url}\n")

    result_gpu = await run_test_with_monitoring("GPU加速", gpu_args, test_url)
    await asyncio.sleep(3)  # 等待系统恢复

    result_no_gpu = await run_test_with_monitoring("软件渲染", no_gpu_args, test_url)

    # 生成对比报告
    print("\n" + "="*60)
    print("📈 性能对比报告")
    print("="*60)

    # 时间对比
    print(f"\n⏱️  时间对比:")
    print(f"{'指标':<20} {'GPU加速':<15} {'软件渲染':<15} {'差异':<15}")
    print("-" * 65)

    for key in ["launch", "navigation", "render", "total"]:
        gpu_val = result_gpu["times"][key]
        no_gpu_val = result_no_gpu["times"][key]
        diff = ((no_gpu_val - gpu_val) / no_gpu_val * 100) if no_gpu_val > 0 else 0

        label_map = {
            "launch": "启动时间",
            "navigation": "导航时间",
            "render": "渲染时间",
            "total": "总时间",
        }

        print(
            f"{label_map[key]:<20} {gpu_val:<14.2f}s {no_gpu_val:<14.2f}s {diff:>+.1f}%"
        )

    # 资源对比
    if result_gpu["resources"] and result_no_gpu["resources"]:
        print(f"\n💻 资源使用对比:")
        print(f"{'指标':<20} {'GPU加速':<15} {'软件渲染':<15} {'差异':<15}")
        print("-" * 65)

        gpu_cpu_avg = result_gpu["resources"]["cpu"]["avg"]
        no_gpu_cpu_avg = result_no_gpu["resources"]["cpu"]["avg"]
        cpu_diff = gpu_cpu_avg - no_gpu_cpu_avg

        print(
            f"{'CPU平均使用':<20} {gpu_cpu_avg:<14.1f}% {no_gpu_cpu_avg:<14.1f}% {cpu_diff:>+.1f}%"
        )

        gpu_mem_avg = result_gpu["resources"]["memory"]["avg"]
        no_gpu_mem_avg = result_no_gpu["resources"]["memory"]["avg"]
        mem_diff = gpu_mem_avg - no_gpu_mem_avg

        print(
            f"{'内存平均使用':<20} {gpu_mem_avg:<14.1f}MB {no_gpu_mem_avg:<14.1f}MB {mem_diff:>+.1f}MB"
        )

        gpu_mem_max = result_gpu["resources"]["memory"]["max"]
        no_gpu_mem_max = result_no_gpu["resources"]["memory"]["max"]
        mem_max_diff = gpu_mem_max - no_gpu_mem_max

        print(
            f"{'内存峰值使用':<20} {gpu_mem_max:<14.1f}MB {no_gpu_mem_max:<14.1f}MB {mem_max_diff:>+.1f}MB"
        )

    # 性能指标对比
    print(f"\n📊 浏览器性能指标对比:")
    print(f"{'指标':<20} {'GPU加速':<15} {'软件渲染':<15}")
    print("-" * 50)

    for key in ["domContentLoaded", "loadComplete", "firstContentfulPaint"]:
        gpu_val = result_gpu["performance_metrics"].get(key, 0)
        no_gpu_val = result_no_gpu["performance_metrics"].get(key, 0)

        label_map = {
            "domContentLoaded": "DOM内容加载",
            "loadComplete": "页面加载完成",
            "firstContentfulPaint": "首次内容绘制",
        }

        if gpu_val > 0 and no_gpu_val > 0:
            print(f"{label_map.get(key, key):<20} {gpu_val:<14.0f}ms {no_gpu_val:<14.0f}ms")

    # 总结建议
    print(f"\n💡 结论:")
    total_improvement = (
        (result_no_gpu["times"]["total"] - result_gpu["times"]["total"])
        / result_no_gpu["times"]["total"]
        * 100
    )

    if total_improvement > 10:
        print("  ✅ GPU加速带来显著性能提升（>10%），强烈建议启用")
    elif total_improvement > 5:
        print("  ✅ GPU加速有一定性能提升（5-10%），建议启用")
    elif total_improvement > -5:
        print("  ℹ️  性能差异不明显（±5%），根据资源情况选择")
    else:
        print("  ⚠️  GPU加速反而降低性能，建议使用软件渲染")
        print("     （可能原因：无GPU硬件、驱动问题、或虚拟化环境限制）")

    if result_gpu["resources"] and result_no_gpu["resources"]:
        mem_increase = gpu_mem_avg - no_gpu_mem_avg
        if mem_increase > 100:
            print(f"  ⚠️  GPU模式额外占用约 {mem_increase:.0f}MB 内存")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
