"""
httpx 异步批量压测工具

单线程异步版本，使用 httpx + asyncio。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TextIO

import httpx

DEFAULT_PROMPT = (
    "Generate a high-resolution wide-angle interior editorial image set in a Scandinavian living room. "
    "The lamp should be clearly visible yet proportionally balanced in the full-room view, placed naturally "
    "and seamlessly integrated into the surroundings. Ensure the lamp, ceiling, furniture, and overall layout "
    "are all visible, showing how the lamp harmoniously fits into the architectural space. It should act as a "
    "refined focal point—adding warmth, style, and realism through its materials and soft light diffusion—without "
    "overwhelming the scene. Use cinematic wide composition, natural soft daylight, and realistic materials. "
    "Include details such as light wood, white walls, linen curtains, boucle/wool throws, simple ceramics, leafy "
    "plants, minimal art and other curated decorative elements to create a refined, relaxed, and authentic lifestyle "
    "atmosphere suitable for editorial or marketing photography."
)


@dataclass
class Config:
    """压测配置"""

    images_dir: Path
    url: str
    prompt: str
    model: str
    n: int
    size: str
    response_format: str
    sample_size: int
    seed: int
    fast_scan: bool
    rps: float
    max_concurrent: int
    timeout: float
    exts: list[str]
    out_jsonl: Path | None
    download_mode: str


@dataclass
class RequestResult:
    """单次请求结果"""

    ok: bool
    status_code: int | None
    latency_s: float
    error: str | None
    payload: dict | None
    image_path: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status_code": self.status_code,
            "latency_s": self.latency_s,
            "error": self.error,
            "payload": self.payload,
            "image_path": self.image_path,
        }


@dataclass
class Stats:
    """统计数据"""

    ok_count: int = 0
    fail_count: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.ok_count + self.fail_count

    @property
    def avg_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.95)
        idx = max(0, min(idx, len(sorted_lat) - 1))
        return sorted_lat[idx]


def scan_images(images_dir: Path, exts: list[str], min_images: int = 0) -> list[Path]:
    """扫描目录中的图片文件

    Args:
        images_dir: 图片目录
        exts: 允许的扩展名列表
        min_images: 最少需要扫描到的图片数量，达到后即停止扫描（0表示扫描全部）
    """
    if not images_dir.is_dir():
        return []

    allowed = {ext.lower().lstrip(".") for ext in exts}
    images = []

    # 使用 os.scandir 而不是 Path.iterdir()，性能更好
    with os.scandir(images_dir) as entries:
        for entry in entries:
            # is_file(follow_symlinks=False) 避免额外的 stat 调用
            if entry.is_file(follow_symlinks=False):
                name = entry.name
                if "." in name:
                    ext = name.rsplit(".", 1)[1].lower()
                    if ext in allowed:
                        images.append(Path(entry.path))
                        # 达到最小数量后停止扫描
                        if min_images > 0 and len(images) >= min_images:
                            break

    return images


async def send_request(
    client: httpx.AsyncClient,
    config: Config,
    image_path: Path,
) -> RequestResult:
    """发送单次 API 请求"""
    start = time.perf_counter()

    try:
        image_bytes = image_path.read_bytes()

        response = await client.post(
            config.url,
            data={
                "prompt": config.prompt,
                "model": config.model,
                "n": str(config.n),
                "size": config.size,
                "response_format": config.response_format,
                "download_mode": config.download_mode,
            },
            files={"images": (image_path.name, image_bytes, "image/png")},
            headers={"accept": "application/json"},
        )

        latency = time.perf_counter() - start

        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {"raw_text": response.text[:2000]}

        return RequestResult(
            ok=(response.status_code == 200),
            status_code=response.status_code,
            latency_s=latency,
            error=None,
            payload=payload,
            image_path=str(image_path),
        )

    except Exception as e:
        latency = time.perf_counter() - start
        return RequestResult(
            ok=False,
            status_code=None,
            latency_s=latency,
            error=str(e),
            payload=None,
            image_path=str(image_path),
        )


class LoadTester:
    """压测执行器"""

    def __init__(self, config: Config):
        self.config = config
        self.stats = Stats()
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._start_time: float = 0.0
        self._out_file: TextIO | None = None

    async def _execute_with_rate_limit(
        self,
        client: httpx.AsyncClient,
        image_path: Path,
        index: int,
    ) -> RequestResult:
        """带速率限制执行请求"""
        # 速率控制
        target_time = self._start_time + (index / self.config.rps)
        delay = target_time - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)

        # 并发控制
        async with self._semaphore:
            result = await send_request(client, self.config, image_path)

        # 更新统计
        self._record_result(result)

        return result

    def _record_result(self, result: RequestResult) -> None:
        """记录结果"""
        self.stats.latencies.append(result.latency_s)

        if result.ok:
            self.stats.ok_count += 1
        else:
            self.stats.fail_count += 1

        # 写入文件
        if self._out_file is not None:
            line = json.dumps(result.to_dict(), ensure_ascii=False)
            self._out_file.write(line + "\n")
            self._out_file.flush()

        # 打印进度
        total = self.stats.total
        sample_size = self.config.sample_size
        if total % 50 == 0 or total == sample_size:
            elapsed = time.perf_counter() - self._start_time
            print(
                f"[progress] {total}/{sample_size} "
                f"ok={self.stats.ok_count} fail={self.stats.fail_count} "
                f"elapsed={elapsed:.1f}s avg={self.stats.avg_latency:.3f}s p95={self.stats.p95_latency:.3f}s"
            )

    async def run(self, images: list[Path]) -> None:
        """执行压测"""
        self._start_time = time.perf_counter()

        # 打开输出文件
        if self.config.out_jsonl:
            self._out_file = open(self.config.out_jsonl, "w", encoding="utf-8")

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                limits=httpx.Limits(
                    max_connections=self.config.max_concurrent + 10,
                    max_keepalive_connections=self.config.max_concurrent,
                ),
            ) as client:
                tasks = [
                    self._execute_with_rate_limit(client, img, i)
                    for i, img in enumerate(images)
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            if self._out_file is not None:
                self._out_file.close()
                self._out_file = None

        # 打印最终结果
        total_time = time.perf_counter() - self._start_time
        achieved_rps = self.stats.total / total_time if total_time > 0 else 0

        print()
        print("=" * 60)
        print(
            f"[summary] total={self.stats.total} ok={self.stats.ok_count} fail={self.stats.fail_count}"
        )
        print(
            f"          time={total_time:.1f}s rps={achieved_rps:.2f} "
            f"avg={self.stats.avg_latency:.3f}s p95={self.stats.p95_latency:.3f}s"
        )
        print("=" * 60)


def parse_args() -> Config:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="httpx 异步批量压测工具")

    data_dir = os.getenv("DATA_DIR", "/app/data")
    default_images_dir = Path(data_dir) / "sample_images"

    parser.add_argument(
        "--images-dir",
        type=Path,
        default=default_images_dir,
        help="图片目录",
    )
    parser.add_argument(
        "--exts",
        default="jpg,jpeg,png,webp",
        help="图片扩展名，逗号分隔",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=30,
        help="采样数量",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子",
    )
    parser.add_argument(
        "--no-fast-scan",
        dest="fast_scan",
        action="store_false",
        default=True,
        help="禁用快速扫描模式，扫描目录中的全部图片（默认启用快速扫描）",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=5.0,
        help="每秒请求数",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=30,
        help="最大并发数",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="请求超时(秒)",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/v1/images/edits",
        help="API 地址",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="提示词",
    )
    parser.add_argument(
        "--model",
        default="gemini-flash",
        # default="gemini-pro",
        help="模型名称",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=1,
        help="生成图片数",
    )
    parser.add_argument(
        "--size",
        default="1024x1024",
        help="图片尺寸",
    )
    parser.add_argument(
        "--response-format",
        default="url",
        help="响应格式",
    )
    parser.add_argument(
        "--out-jsonl",
        type=Path,
        default=Path(data_dir) / "out_files_httpx.jsonl",
        help="输出文件路径",
    )
    parser.add_argument(
        "--download-mode",
        choices=["preview", "hd", "both"],
        default="both",
        help="图片下载模式 (preview, hd, both)",
    )

    args = parser.parse_args()

    return Config(
        images_dir=args.images_dir,
        url=args.url,
        prompt=args.prompt,
        model=args.model,
        n=args.n,
        size=args.size,
        response_format=args.response_format,
        sample_size=args.sample_size,
        seed=args.seed,
        fast_scan=args.fast_scan,
        rps=args.rps,
        max_concurrent=args.max_concurrent,
        timeout=args.timeout,
        exts=[e.strip() for e in args.exts.split(",") if e.strip()],
        out_jsonl=args.out_jsonl,
        download_mode=args.download_mode,
    )


async def main() -> int:
    """主入口"""
    config = parse_args()

    # 验证目录
    if not config.images_dir.exists():
        print(f"Error: images-dir not found: {config.images_dir}", file=sys.stderr)
        return 1

    # 扫描图片
    # 在快速扫描模式下，扫描到 sample_size * 10 的图片数量后停止
    # 这样既能保证随机性（有10倍于采样数的候选），又能快速启动
    min_images = config.sample_size * 10 if config.fast_scan else 0
    if config.fast_scan:
        print(f"[scan] 快速扫描模式：扫描到 {min_images} 个图片后停止...")
    else:
        print(f"[scan] 完整扫描模式：扫描全部图片...")

    scan_start = time.perf_counter()
    all_images = scan_images(config.images_dir, config.exts, min_images)
    scan_time = time.perf_counter() - scan_start

    if not all_images:
        print(f"Error: no images found in {config.images_dir}", file=sys.stderr)
        return 1

    print(f"[scan] 扫描完成，耗时 {scan_time:.1f}s，找到 {len(all_images)} 个图片")

    # 随机采样
    rng = random.Random(config.seed)
    sample_size = min(config.sample_size, len(all_images))
    images = rng.sample(all_images, sample_size)

    # 打印配置
    print(f"[config] images: {len(all_images)} total, {sample_size} sampled")
    print(
        f"[config] rps={config.rps} concurrent={config.max_concurrent} timeout={config.timeout}s"
    )
    print(f"[config] url={config.url}")
    print()

    # 执行压测
    tester = LoadTester(config)
    await tester.run(images)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
