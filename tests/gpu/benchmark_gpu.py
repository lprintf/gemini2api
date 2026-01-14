"""
GPU性能对比测试脚本

功能：
1. 对比启用/禁用GPU的资源消耗（CPU、内存）
2. 对比启用/禁用GPU的性能（页面加载时间、渲染时间）
3. 生成详细的性能报告

使用方法：
    python benchmark_gpu.py --duration 60 --iterations 10
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import psutil
from playwright.async_api import async_playwright


class ResourceMonitor:
    """资源监控器"""

    def __init__(self, pid: int, interval: float = 0.5):
        self.pid = pid
        self.interval = interval
        self.process = psutil.Process(pid)
        self.samples: List[Dict] = []
        self.monitoring = False
        self._task = None

    async def start(self):
        """开始监控"""
        self.monitoring = True
        self._task = asyncio.create_task(self._monitor())

    async def stop(self):
        """停止监控"""
        self.monitoring = False
        if self._task:
            await self._task

    async def _monitor(self):
        """监控循环"""
        while self.monitoring:
            try:
                # 获取进程及子进程的资源使用
                cpu_percent = self.process.cpu_percent()
                memory_info = self.process.memory_info()

                # 包括子进程
                children = self.process.children(recursive=True)
                total_memory = memory_info.rss
                total_cpu = cpu_percent

                for child in children:
                    try:
                        total_cpu += child.cpu_percent()
                        total_memory += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                sample = {
                    "timestamp": time.time(),
                    "cpu_percent": total_cpu,
                    "memory_mb": total_memory / 1024 / 1024,
                    "num_threads": self.process.num_threads(),
                    "num_children": len(children),
                }
                self.samples.append(sample)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

            await asyncio.sleep(self.interval)

    def get_stats(self) -> Dict:
        """获取统计数据"""
        if not self.samples:
            return {}

        cpu_values = [s["cpu_percent"] for s in self.samples]
        memory_values = [s["memory_mb"] for s in self.samples]

        return {
            "cpu": {
                "avg": sum(cpu_values) / len(cpu_values),
                "max": max(cpu_values),
                "min": min(cpu_values),
            },
            "memory": {
                "avg": sum(memory_values) / len(memory_values),
                "max": max(memory_values),
                "min": min(memory_values),
            },
            "samples_count": len(self.samples),
        }


class BrowserBenchmark:
    """浏览器性能测试"""

    def __init__(self, use_gpu: bool = True):
        self.use_gpu = use_gpu
        self.results: List[Dict] = []

    async def run_single_test(self, url: str) -> Dict:
        """运行单次测试"""
        async with async_playwright() as p:
            # 配置浏览器参数
            if self.use_gpu:
                args = [
                    "--use-gl=egl",
                    "--enable-gpu-rasterization",
                    "--enable-accelerated-2d-canvas",
                    "--enable-accelerated-video-decode",
                    "--no-sandbox",
                ]
            else:
                args = [
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]

            # 启动浏览器
            browser = await p.chromium.launch(headless=True, args=args)

            # 获取浏览器进程PID
            # Chromium browser对象没有直接暴露PID，我们需要通过其他方式获取
            context = await browser.new_context()
            page = await context.new_page()

            # 启动资源监控
            # 注意：需要找到浏览器进程的PID
            browser_pid = None
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if "chromium" in proc.info["name"].lower():
                        cmdline = proc.info.get("cmdline", [])
                        if cmdline and "--enable-automation" in " ".join(cmdline):
                            browser_pid = proc.info["pid"]
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            monitor = None
            if browser_pid:
                monitor = ResourceMonitor(browser_pid)
                await monitor.start()

            # 性能测试
            start_time = time.time()

            try:
                # 导航到页面
                nav_start = time.time()
                await page.goto(url, wait_until="networkidle", timeout=30000)
                nav_duration = time.time() - nav_start

                # 等待页面完全加载
                await page.wait_for_load_state("load")

                # 获取性能指标
                performance_timing = await page.evaluate(
                    """() => {
                        const timing = performance.timing;
                        const navigation = performance.getEntriesByType('navigation')[0];
                        return {
                            domContentLoaded: timing.domContentLoadedEventEnd - timing.navigationStart,
                            loadComplete: timing.loadEventEnd - timing.navigationStart,
                            domInteractive: timing.domInteractive - timing.navigationStart,
                            firstPaint: navigation ? navigation.responseEnd - navigation.requestStart : 0,
                        };
                    }"""
                )

                # 执行一些交互操作来测试GPU加速效果
                await page.evaluate(
                    """() => {
                        // 创建大量DOM元素测试渲染性能
                        const container = document.createElement('div');
                        for (let i = 0; i < 1000; i++) {
                            const div = document.createElement('div');
                            div.style.cssText = 'width: 100px; height: 100px; background: linear-gradient(45deg, red, blue); margin: 5px; display: inline-block;';
                            container.appendChild(div);
                        }
                        document.body.appendChild(container);
                    }"""
                )

                # 等待渲染完成
                await asyncio.sleep(2)

                test_duration = time.time() - start_time

                result = {
                    "success": True,
                    "navigation_time": nav_duration,
                    "test_duration": test_duration,
                    "performance": performance_timing,
                }

            except Exception as e:
                result = {
                    "success": False,
                    "error": str(e),
                    "test_duration": time.time() - start_time,
                }

            # 停止监控
            if monitor:
                await monitor.stop()
                result["resources"] = monitor.get_stats()

            await browser.close()
            return result

    async def run_benchmark(
        self, url: str, iterations: int = 10, delay: float = 2.0
    ) -> Dict:
        """运行完整基准测试"""
        print(f"\n{'='*60}")
        print(f"开始测试: {'GPU 加速' if self.use_gpu else '软件渲染'}")
        print(f"{'='*60}")

        results = []
        for i in range(iterations):
            print(f"第 {i+1}/{iterations} 次测试...")
            result = await self.run_single_test(url)
            results.append(result)

            if i < iterations - 1:
                await asyncio.sleep(delay)

        # 计算统计数据
        successful_results = [r for r in results if r.get("success")]

        if not successful_results:
            return {"error": "所有测试都失败了", "results": results}

        # 计算平均值
        avg_nav_time = sum(r["navigation_time"] for r in successful_results) / len(
            successful_results
        )
        avg_test_duration = sum(r["test_duration"] for r in successful_results) / len(
            successful_results
        )

        # 资源统计
        resource_stats = [r["resources"] for r in successful_results if "resources" in r]
        if resource_stats:
            avg_cpu = sum(r["cpu"]["avg"] for r in resource_stats) / len(resource_stats)
            max_cpu = max(r["cpu"]["max"] for r in resource_stats)
            avg_memory = sum(r["memory"]["avg"] for r in resource_stats) / len(
                resource_stats
            )
            max_memory = max(r["memory"]["max"] for r in resource_stats)
        else:
            avg_cpu = max_cpu = avg_memory = max_memory = 0

        summary = {
            "mode": "GPU 加速" if self.use_gpu else "软件渲染",
            "iterations": iterations,
            "successful": len(successful_results),
            "failed": len(results) - len(successful_results),
            "performance": {
                "avg_navigation_time": avg_nav_time,
                "avg_test_duration": avg_test_duration,
            },
            "resources": {
                "cpu": {"avg": avg_cpu, "max": max_cpu},
                "memory_mb": {"avg": avg_memory, "max": max_memory},
            },
            "raw_results": results,
        }

        return summary


async def main():
    parser = argparse.ArgumentParser(description="GPU性能对比测试")
    parser.add_argument(
        "--url",
        default="https://gemini.google.com",
        help="测试URL (默认: https://gemini.google.com)",
    )
    parser.add_argument(
        "--iterations", type=int, default=10, help="每种模式测试次数 (默认: 10)"
    )
    parser.add_argument(
        "--delay", type=float, default=2.0, help="测试间隔秒数 (默认: 2.0)"
    )
    parser.add_argument(
        "--output",
        default="benchmark_results.json",
        help="结果输出文件 (默认: benchmark_results.json)",
    )

    args = parser.parse_args()

    # 测试GPU模式
    gpu_benchmark = BrowserBenchmark(use_gpu=True)
    gpu_results = await gpu_benchmark.run_benchmark(
        args.url, args.iterations, args.delay
    )

    # 测试非GPU模式
    no_gpu_benchmark = BrowserBenchmark(use_gpu=False)
    no_gpu_results = await no_gpu_benchmark.run_benchmark(
        args.url, args.iterations, args.delay
    )

    # 生成对比报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "test_config": {
            "url": args.url,
            "iterations": args.iterations,
            "delay": args.delay,
        },
        "gpu_enabled": gpu_results,
        "gpu_disabled": no_gpu_results,
    }

    # 计算性能差异
    if gpu_results.get("performance") and no_gpu_results.get("performance"):
        gpu_perf = gpu_results["performance"]
        no_gpu_perf = no_gpu_results["performance"]

        perf_improvement = {
            "navigation_time_improvement": (
                (no_gpu_perf["avg_navigation_time"] - gpu_perf["avg_navigation_time"])
                / no_gpu_perf["avg_navigation_time"]
                * 100
            ),
            "test_duration_improvement": (
                (no_gpu_perf["avg_test_duration"] - gpu_perf["avg_test_duration"])
                / no_gpu_perf["avg_test_duration"]
                * 100
            ),
        }

        # 资源对比
        if gpu_results.get("resources") and no_gpu_results.get("resources"):
            gpu_res = gpu_results["resources"]
            no_gpu_res = no_gpu_results["resources"]

            perf_improvement["cpu_difference"] = (
                gpu_res["cpu"]["avg"] - no_gpu_res["cpu"]["avg"]
            )
            perf_improvement["memory_difference"] = (
                gpu_res["memory_mb"]["avg"] - no_gpu_res["memory_mb"]["avg"]
            )

        report["performance_comparison"] = perf_improvement

    # 保存结果
    output_path = Path(args.output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 打印摘要
    print(f"\n{'='*60}")
    print("测试完成！结果摘要：")
    print(f"{'='*60}")

    print(f"\n📊 GPU 加速模式:")
    if gpu_results.get("performance"):
        print(f"  ⏱️  平均导航时间: {gpu_results['performance']['avg_navigation_time']:.2f}s")
        print(f"  ⏱️  平均测试时长: {gpu_results['performance']['avg_test_duration']:.2f}s")
    if gpu_results.get("resources"):
        print(f"  💻 平均CPU使用: {gpu_results['resources']['cpu']['avg']:.1f}%")
        print(f"  💾 平均内存使用: {gpu_results['resources']['memory_mb']['avg']:.1f}MB")

    print(f"\n📊 软件渲染模式:")
    if no_gpu_results.get("performance"):
        print(f"  ⏱️  平均导航时间: {no_gpu_results['performance']['avg_navigation_time']:.2f}s")
        print(f"  ⏱️  平均测试时长: {no_gpu_results['performance']['avg_test_duration']:.2f}s")
    if no_gpu_results.get("resources"):
        print(f"  💻 平均CPU使用: {no_gpu_results['resources']['cpu']['avg']:.1f}%")
        print(f"  💾 平均内存使用: {no_gpu_results['resources']['memory_mb']['avg']:.1f}MB")

    if report.get("performance_comparison"):
        comp = report["performance_comparison"]
        print(f"\n📈 性能对比:")
        print(f"  导航时间改善: {comp.get('navigation_time_improvement', 0):.1f}%")
        print(f"  测试时长改善: {comp.get('test_duration_improvement', 0):.1f}%")
        print(f"  CPU差异: {comp.get('cpu_difference', 0):+.1f}%")
        print(f"  内存差异: {comp.get('memory_difference', 0):+.1f}MB")

    print(f"\n详细结果已保存到: {output_path.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
