"""
测试 Playwright 下载图片

使用方法：
    python test/codegen_persistent.py [user_id]

参数：
    user_id: 可选，指定浏览器用户目录编号（默认为 0）

示例：
    python test/codegen_persistent.py       # 使用用户 0
    python test/codegen_persistent.py 1     # 使用用户 1
    python test/codegen_persistent.py 2     # 使用用户 2

这会使用已登录的浏览器数据，提供交互式命令测试下载功能。
"""

import argparse
import asyncio
import base64
import hashlib
import math
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


def detect_image_format(data: bytes) -> str:
    """根据文件头检测图片格式"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    elif data[:2] == b"\xff\xd8":
        return "jpg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    else:
        return "bin"


def generate_human_path(start_x, start_y, end_x, end_y, steps=None):
    """
    生成拟人鼠标移动轨迹，使用贝塞尔曲线+随机抖动
    返回 [(x, y), ...] 坐标列表
    """
    distance = math.sqrt((end_x - start_x) ** 2 + (end_y - start_y) ** 2)

    # 根据距离自动计算步数
    if steps is None:
        steps = max(10, min(50, int(distance / 20)))

    # 生成随机控制点（贝塞尔曲线）
    # 控制点偏移量与距离成正比，增加自然感
    ctrl_offset = distance * 0.3
    ctrl1_x = start_x + (end_x - start_x) * 0.3 + random.uniform(-ctrl_offset, ctrl_offset)
    ctrl1_y = start_y + (end_y - start_y) * 0.3 + random.uniform(-ctrl_offset, ctrl_offset)
    ctrl2_x = start_x + (end_x - start_x) * 0.7 + random.uniform(-ctrl_offset, ctrl_offset)
    ctrl2_y = start_y + (end_y - start_y) * 0.7 + random.uniform(-ctrl_offset, ctrl_offset)

    path = []
    for i in range(steps + 1):
        t = i / steps

        # 三次贝塞尔曲线
        x = (
            (1 - t) ** 3 * start_x
            + 3 * (1 - t) ** 2 * t * ctrl1_x
            + 3 * (1 - t) * t**2 * ctrl2_x
            + t**3 * end_x
        )
        y = (
            (1 - t) ** 3 * start_y
            + 3 * (1 - t) ** 2 * t * ctrl1_y
            + 3 * (1 - t) * t**2 * ctrl2_y
            + t**3 * end_y
        )

        # 添加小幅随机抖动（中间点抖动大，两端抖动小）
        jitter = 2 * math.sin(t * math.pi)  # 中间最大
        x += random.uniform(-jitter, jitter)
        y += random.uniform(-jitter, jitter)

        path.append((int(x), int(y)))

    # 确保最后一个点精确到达目标
    path[-1] = (int(end_x), int(end_y))

    return path


async def get_last_response_images(page) -> list[str]:
    """获取最后一轮对话中的图片URL"""
    containers = await page.query_selector_all("model-response")
    if not containers:
        return []

    last_container = containers[-1]
    images = await last_container.query_selector_all("img")

    urls = []
    for img in images:
        src = await img.get_attribute("src")
        if src and "googleusercontent" in src and "/a/ACg8oc" not in src:
            urls.append(src)

    return urls


async def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="Playwright 下载测试 - 交互式命令工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python tests/codegen_persistent.py       # 使用用户 0
  python tests/codegen_persistent.py 1     # 使用用户 1
  python tests/codegen_persistent.py 2     # 使用用户 2
        """
    )
    parser.add_argument(
        "user_id",
        nargs="?",
        default="0",
        help="浏览器用户目录编号（默认: 0）"
    )
    args = parser.parse_args()

    # 配置
    test_url = "https://gemini.google.com/app"
    user_data_dir = Path(__file__).parent.parent / "data" / "browser_data" / args.user_id
    output_dir = Path(__file__).parent.parent / "data" / "test_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Playwright 下载测试")
    print("=" * 60)
    print(f"用户ID: {args.user_id}")
    print(f"测试页面: {test_url}")
    print(f"用户数据目录: {user_data_dir}")
    print(f"输出目录: {output_dir}")
    print()

    async with async_playwright() as p:
        # 构建启动参数
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ]

        # Wayland 支持（参考 gemini_browser.py）
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        if wayland_display:
            launch_args.extend([
                "--ozone-platform=wayland",
                "--enable-features=UseOzonePlatform",
            ])
            print(f"检测到 Wayland 环境: {wayland_display}")

        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            args=launch_args,
            viewport={"width": 1280, "height": 900},
            slow_mo=100,
        )

        page = context.pages[0] if context.pages else await context.new_page()

        print("正在打开测试页面...")
        await page.goto(test_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        print("\n页面已加载!")
        print()
        print("=" * 60)
        print("交互模式 - 输入 help 查看命令")
        print("=" * 60)

        # 创建 editor 实例用于测试
        editor = None

        while True:
            try:
                cmd = input("\n> ").strip()

                if cmd == "quit" or cmd == "exit":
                    break

                elif cmd == "pause":
                    print("打开 Playwright Inspector...")
                    await page.pause()

                elif cmd == "buttons":
                    buttons = await page.query_selector_all("button")
                    print(f"找到 {len(buttons)} 个按钮:")
                    for i, btn in enumerate(buttons[:30]):
                        aria = await btn.get_attribute("aria-label") or ""
                        text = (await btn.text_content() or "").strip()[:30]
                        visible = await btn.is_visible()
                        if visible and (aria or text):
                            print(f"  [{i}] aria='{aria}' text='{text}'")

                elif cmd == "images":
                    # 只列出最后一轮对话中的图片
                    urls = await get_last_response_images(page)
                    if urls:
                        print(f"最后一轮对话中找到 {len(urls)} 张图片:")
                        for i, url in enumerate(urls):
                            print(f"  [{i}] {url[:100]}...")
                    else:
                        print("最后一轮对话中未找到生成的图片")

                elif cmd.startswith("fetch "):
                    # 使用 page.request.get 下载指定索引的图片
                    try:
                        index = int(cmd[6:])
                        urls = await get_last_response_images(page)

                        if index >= len(urls):
                            print(f"索引 {index} 超出范围（共 {len(urls)} 张）")
                            continue

                        url = urls[index]
                        print(f"正在下载图片 [{index}] (page.request.get)...")
                        print(f"  URL: {url[:80]}...")

                        # 使用 page.request.get
                        response = await page.request.get(url)

                        if response.ok:
                            image_bytes = await response.body()
                            # 根据文件内容检测格式
                            fmt = detect_image_format(image_bytes)
                            save_path = output_dir / f"fetch_{index}.{fmt}"
                            with open(save_path, "wb") as f:
                                f.write(image_bytes)
                            print(f"✓ 下载成功: {save_path}")
                            print(
                                f"  格式: {fmt.upper()}, 大小: {len(image_bytes) / 1024:.1f} KB"
                            )
                        else:
                            print(f"❌ 下载失败，HTTP状态: {response.status}")

                    except ValueError:
                        print("用法: fetch <index>")

                elif cmd.startswith("preview "):
                    # 快速预览下载：使用 page.request.get 下载图片，计算 hash，保存为 jpg
                    # 返回 {日期}/{hash} 格式的路径（用于后续高清下载）
                    try:
                        index = int(cmd[8:])
                        urls = await get_last_response_images(page)

                        if index >= len(urls):
                            print(f"索引 {index} 超出范围（共 {len(urls)} 张）")
                            continue

                        url = urls[index]
                        print(f"正在快速下载预览图 [{index}]...")
                        print(f"  URL: {url[:80]}...")

                        start_time = time.time()

                        # 1. 使用 page.request.get 快速下载
                        response = await page.request.get(url)

                        if not response.ok:
                            print(f"❌ 下载失败，HTTP状态: {response.status}")
                            continue

                        image_bytes = await response.body()
                        download_time = time.time() - start_time

                        # 2. 计算 hash (base64url, 去除填充)
                        sha256_hash = hashlib.sha256(image_bytes).digest()
                        file_hash = base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")

                        # 3. 保存为原始格式（检测实际格式）
                        fmt = detect_image_format(image_bytes)
                        date_str = datetime.now().strftime("%Y%m%d")
                        date_dir = output_dir / date_str
                        date_dir.mkdir(parents=True, exist_ok=True)

                        save_path = date_dir / f"{file_hash}.{fmt}"
                        with open(save_path, "wb") as f:
                            f.write(image_bytes)

                        total_time = time.time() - start_time

                        print("\n✓ 预览图已保存")
                        print(f"  路径: {save_path}")
                        print(f"  格式: {fmt.upper()}, 大小: {len(image_bytes)/1024:.1f}KB")
                        print(f"  下载耗时: {download_time:.3f}s, 总耗时: {total_time:.3f}s")
                        print(f"\n  用于高清请求的参数: {date_str}/{file_hash}")
                        print(f"  页面URL (用于匹配): {url[:60]}...")

                        # 保存 URL 映射到临时变量（用于 hd 命令）
                        if not hasattr(main, "preview_cache"):
                            main.preview_cache = {}
                        main.preview_cache[f"{date_str}/{file_hash}"] = {
                            "url": url,
                            "index": index,
                            "path": str(save_path),
                        }

                    except ValueError:
                        print("用法: preview <index>")

                elif cmd.startswith("hd "):
                    # 高清下载：根据预览图的 date/hash 找到对应图片，hover 下载高清版
                    try:
                        from io import BytesIO
                        from PIL import Image

                        arg = cmd[3:].strip()
                        if "/" not in arg:
                            print("用法: hd <date>/<hash>")
                            print("示例: hd 20260106/abc123def456")
                            continue

                        parts = arg.split("/")
                        date_str, file_hash = parts[0], parts[1]

                        print(f"正在查找预览图: {date_str}/{file_hash}...")

                        # 方法1: 从 preview_cache 获取（如果刚执行过 preview 命令）
                        cache_key = f"{date_str}/{file_hash}"
                        target_url = None

                        if hasattr(main, "preview_cache") and cache_key in main.preview_cache:
                            cached = main.preview_cache[cache_key]
                            target_url = cached["url"]
                            print(f"  从缓存获取 URL: {target_url[:60]}...")
                        else:
                            # 方法2: 遍历页面上的图片，计算 hash 匹配
                            print("  缓存未命中，正在遍历页面图片匹配 hash...")
                            urls = await get_last_response_images(page)

                            for i, url in enumerate(urls):
                                response = await page.request.get(url)
                                if response.ok:
                                    img_bytes = await response.body()
                                    img_hash = base64.urlsafe_b64encode(
                                        hashlib.sha256(img_bytes).digest()
                                    ).decode().rstrip("=")
                                    if img_hash == file_hash:
                                        target_url = url
                                        print(f"  找到匹配图片 [{i}]: {url[:60]}...")
                                        break

                        if target_url is None:
                            print(f"❌ 未找到匹配的图片: {file_hash}")
                            continue

                        # 懒加载 editor
                        if editor is None:
                            from core.image_editor import GeminiImageEditor
                            editor = GeminiImageEditor.__new__(GeminiImageEditor)
                            editor.page = page

                        print("\n正在通过 hover 下载按钮获取高清图...")
                        start_time = time.time()

                        # 使用 hover 下载按钮获取高清图
                        hd_bytes = await editor._download_via_hover_button(target_url, "no_wait")

                        if not hd_bytes:
                            print("❌ 高清图下载失败（hover 按钮未就绪或超时）")
                            continue

                        download_time = time.time() - start_time

                        # 转换为 webp 并保存
                        img = Image.open(BytesIO(hd_bytes))
                        width, height = img.size

                        webp_buffer = BytesIO()
                        img.save(webp_buffer, "WEBP", lossless=True)
                        webp_data = webp_buffer.getvalue()

                        # 计算高清图的 hash
                        hd_hash = base64.urlsafe_b64encode(
                            hashlib.sha256(webp_data).digest()
                        ).decode().rstrip("=")

                        # 保存高清图
                        date_dir = output_dir / date_str
                        date_dir.mkdir(parents=True, exist_ok=True)
                        hd_path = date_dir / f"{file_hash}_hd.webp"

                        with open(hd_path, "wb") as f:
                            f.write(webp_data)

                        total_time = time.time() - start_time

                        print("\n✓ 高清图已保存")
                        print(f"  路径: {hd_path}")
                        print(f"  尺寸: {width}x{height}")
                        print(f"  原始大小: {len(hd_bytes)/1024:.1f}KB → WebP: {len(webp_data)/1024:.1f}KB")
                        print(f"  下载耗时: {download_time:.3f}s, 总耗时: {total_time:.3f}s")
                        print(f"  高清图 hash: {hd_hash[:16]}...")

                    except ValueError as e:
                        print("用法: hd <date>/<hash>")
                        print(f"错误: {e}")
                    except ImportError:
                        print("❌ 需要安装 Pillow: pip install Pillow")

                elif cmd.startswith("flow "):
                    # 完整流程测试：模拟 预览 → 高清 的完整流程
                    try:
                        from io import BytesIO
                        from PIL import Image

                        index = int(cmd[5:])
                        urls = await get_last_response_images(page)

                        if index >= len(urls):
                            print(f"索引 {index} 超出范围（共 {len(urls)} 张）")
                            continue

                        url = urls[index]

                        print("=" * 60)
                        print("完整流程测试：预览 → 高清")
                        print("=" * 60)
                        print(f"图片索引: {index}")
                        print(f"URL: {url[:60]}...")
                        print()

                        total_start = time.time()

                        # ========== 阶段1: 快速预览下载 ==========
                        print("=== 阶段1: 快速预览下载 ===")
                        preview_start = time.time()

                        response = await page.request.get(url)
                        if not response.ok:
                            print(f"❌ 预览下载失败，HTTP状态: {response.status}")
                            continue

                        preview_bytes = await response.body()
                        _ = time.time() - preview_start  # preview_download_time (unused)

                        # 计算 hash
                        sha256_hash = hashlib.sha256(preview_bytes).digest()
                        file_hash = base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")

                        # 保存预览图
                        fmt = detect_image_format(preview_bytes)
                        date_str = datetime.now().strftime("%Y%m%d")
                        date_dir = output_dir / date_str
                        date_dir.mkdir(parents=True, exist_ok=True)

                        preview_path = date_dir / f"{file_hash}.{fmt}"
                        with open(preview_path, "wb") as f:
                            f.write(preview_bytes)

                        preview_total_time = time.time() - preview_start

                        print("✓ 预览图下载完成")
                        print(f"  路径: {preview_path}")
                        print(f"  大小: {len(preview_bytes)/1024:.1f}KB")
                        print(f"  耗时: {preview_total_time:.3f}s")
                        print()
                        print(f">>> 返回给客户端: {date_str}/{file_hash}")
                        print(">>> 客户端可立即使用预览图")
                        print()

                        # ========== 阶段2: 高清下载 ==========
                        print("=== 阶段2: 高清下载 ===")
                        hd_start = time.time()

                        # 懒加载 editor
                        if editor is None:
                            from core.image_editor import GeminiImageEditor
                            editor = GeminiImageEditor.__new__(GeminiImageEditor)
                            editor.page = page

                        # 使用 hover 下载按钮获取高清图
                        hd_bytes = await editor._download_via_hover_button(url, "no_wait")

                        if not hd_bytes:
                            print("❌ 高清图下载失败")
                            continue

                        _ = time.time() - hd_start  # hd_download_time (unused)

                        # 转换为 webp
                        img = Image.open(BytesIO(hd_bytes))
                        width, height = img.size

                        webp_buffer = BytesIO()
                        img.save(webp_buffer, "WEBP", lossless=True)
                        webp_data = webp_buffer.getvalue()

                        # 保存高清图
                        hd_path = date_dir / f"{file_hash}_hd.webp"
                        with open(hd_path, "wb") as f:
                            f.write(webp_data)

                        hd_total_time = time.time() - hd_start
                        total_time = time.time() - total_start

                        print("✓ 高清图下载完成")
                        print(f"  路径: {hd_path}")
                        print(f"  尺寸: {width}x{height}")
                        print(f"  大小: {len(hd_bytes)/1024:.1f}KB → {len(webp_data)/1024:.1f}KB (WebP)")
                        print(f"  耗时: {hd_total_time:.3f}s")
                        print()

                        # ========== 总结 ==========
                        print("=" * 60)
                        print("流程测试完成")
                        print("=" * 60)
                        print(f"预览图: {preview_path}")
                        print(f"  大小: {len(preview_bytes)/1024:.1f}KB, 耗时: {preview_total_time:.3f}s")
                        print(f"高清图: {hd_path}")
                        print(f"  大小: {len(webp_data)/1024:.1f}KB, 耗时: {hd_total_time:.3f}s")
                        print()
                        print(f"总耗时: {total_time:.3f}s")
                        print(f"  其中预览: {preview_total_time:.3f}s ({preview_total_time/total_time*100:.1f}%)")
                        print(f"  其中高清: {hd_total_time:.3f}s ({hd_total_time/total_time*100:.1f}%)")

                    except ValueError:
                        print("用法: flow <index>")
                    except ImportError:
                        print("❌ 需要安装 Pillow: pip install Pillow")

                elif cmd.startswith("webp "):
                    # 使用 download_image_as_webp 测试（先 hover 下载按钮，再回退到 request）
                    # 支持语法: webp <index> [click_method]
                    # 示例: webp 0 js / webp 0 force / webp 0 no_wait / webp 0 normal
                    try:
                        parts = cmd[5:].strip().split()
                        if not parts:
                            print("用法: webp <index> [js|force|no_wait|normal]")
                            continue

                        index = int(parts[0])
                        click_method = parts[1] if len(parts) > 1 else "js"

                        if click_method not in ["js", "force", "no_wait", "normal"]:
                            print("点击方法必须是: js, force, no_wait, normal")
                            continue

                        urls = await get_last_response_images(page)

                        if index >= len(urls):
                            print(f"索引 {index} 超出范围（共 {len(urls)} 张）")
                            continue

                        url = urls[index]
                        print(f"正在下载图片 [{index}] (download_image_as_webp)...")
                        print(f"  URL: {url[:80]}...")
                        print(f"  点击方法: {click_method}")

                        # 懒加载 editor
                        if editor is None:
                            from core.image_editor import GeminiImageEditor

                            editor = GeminiImageEditor.__new__(GeminiImageEditor)
                            editor.page = page

                        save_path = output_dir / f"webp_{index}_{click_method}.webp"
                        success = await editor.download_image_as_webp(
                            url, str(save_path), click_method=click_method
                        )

                        if success:
                            print("✓ WebP 下载测试完成")
                        else:
                            print("❌ WebP 下载失败")

                    except ValueError:
                        print("用法: webp <index> [js|force|no_wait|normal]")

                elif cmd == "download":
                    # 下载最后一轮对话中的所有图片（使用 request API）
                    urls = await get_last_response_images(page)

                    if not urls:
                        print("最后一轮对话中未找到可下载的图片")
                        continue

                    print(f"正在下载 {len(urls)} 张图片 (page.request.get)...")

                    for i, url in enumerate(urls):
                        print(f"  [{i+1}/{len(urls)}] 下载中...")
                        try:
                            response = await page.request.get(url)
                            if response.ok:
                                image_bytes = await response.body()
                                fmt = detect_image_format(image_bytes)
                                save_path = output_dir / f"generated_{i+1}.{fmt}"
                                with open(save_path, "wb") as f:
                                    f.write(image_bytes)
                                print(
                                    f"    ✓ {save_path} ({fmt.upper()}, {len(image_bytes)/1024:.1f}KB)"
                                )
                            else:
                                print(f"    ❌ HTTP {response.status}")
                        except Exception as e:
                            print(f"    ❌ {e}")

                    print(f"\n✓ 下载完成，输出目录: {output_dir}")

                elif cmd == "webp_all":
                    # 使用 download_image_as_webp 下载所有图片
                    urls = await get_last_response_images(page)

                    if not urls:
                        print("最后一轮对话中未找到可下载的图片")
                        continue

                    # 懒加载 editor
                    if editor is None:
                        from core.image_editor import GeminiImageEditor

                        editor = GeminiImageEditor.__new__(GeminiImageEditor)
                        editor.page = page

                    print(f"正在下载 {len(urls)} 张图片 (download_image_as_webp)...")

                    for i, url in enumerate(urls):
                        print(f"\n[{i+1}/{len(urls)}] 下载中...")
                        save_path = output_dir / f"webp_all_{i+1}.webp"
                        await editor.download_image_as_webp(url, str(save_path))

                    print(f"\n✓ 下载完成，输出目录: {output_dir}")

                elif cmd.startswith("model "):
                    # 测试模型切换功能
                    model_name = cmd[6:].strip()
                    if model_name not in ["Pro", "Fast"]:
                        print("用法: model <Pro|Fast>")
                        continue

                    # 懒加载 enhanced editor
                    if editor is None:
                        from core.enhanced_editor import EnhancedGeminiImageEditor

                        enhanced_editor = EnhancedGeminiImageEditor.__new__(
                            EnhancedGeminiImageEditor
                        )
                        enhanced_editor.page = page
                        enhanced_editor.enable_logging = True
                        enhanced_editor.event_log = []
                    else:
                        # 如果已有 editor，创建增强版
                        from core.enhanced_editor import EnhancedGeminiImageEditor

                        enhanced_editor = EnhancedGeminiImageEditor.__new__(
                            EnhancedGeminiImageEditor
                        )
                        enhanced_editor.page = page
                        enhanced_editor.enable_logging = True
                        enhanced_editor.event_log = []

                    print(f"正在切换到 {model_name} 模型...")
                    success = await enhanced_editor.ensure_model_selection(model_name)
                    if success:
                        print(f"✓ 成功切换到 {model_name} 模型")
                    else:
                        print(f"❌ 切换到 {model_name} 模型失败")

                elif cmd.startswith("env "):
                    # 测试页面环境准备（开启新对话+模型选择+激活图片生成，不上传图片和文本）
                    # 解析参数：env [model]
                    model_name = cmd[4:].strip() or "Fast"

                    if model_name not in ["Pro", "Fast"]:
                        print("用法: env [Pro|Fast]")
                        print("示例: env Fast")
                        continue

                    # 懒加载 enhanced editor
                    if editor is None:
                        from core.enhanced_editor import EnhancedGeminiImageEditor

                        enhanced_editor = EnhancedGeminiImageEditor.__new__(
                            EnhancedGeminiImageEditor
                        )
                        enhanced_editor.page = page
                        enhanced_editor.enable_logging = True
                        enhanced_editor.event_log = []
                    else:
                        from core.enhanced_editor import EnhancedGeminiImageEditor

                        if not isinstance(editor, EnhancedGeminiImageEditor):
                            enhanced_editor = EnhancedGeminiImageEditor.__new__(
                                EnhancedGeminiImageEditor
                            )
                            enhanced_editor.page = page
                            enhanced_editor.enable_logging = True
                            enhanced_editor.event_log = []
                        else:
                            enhanced_editor = editor

                    print("=" * 60)
                    print("测试页面环境准备")
                    print("=" * 60)
                    print(f"模型: {model_name}")
                    print()

                    total_start = time.time()

                    try:
                        # 使用 prepare_page_environment 方法
                        success = await enhanced_editor.prepare_page_environment(
                            model=model_name,
                            temporary_chat=False,
                        )

                        total_time = time.time() - total_start
                        print(f"\n总耗时: {total_time:.3f}s")
                        print("=" * 60)

                        if success:
                            print("✓ 页面环境准备完成")
                        else:
                            print("❌ 页面环境准备失败")

                    except Exception as e:
                        print(f"\n❌ 环境准备过程出错: {e}")
                        import traceback

                        traceback.print_exc()

                elif cmd.startswith("prepare "):
                    # 测试准备阶段（上传+模型选择+输入+激活，但不提交）
                    # 解析参数：prepare <image_path> <prompt> [model]
                    parts = cmd[8:].strip().split(maxsplit=2)
                    if len(parts) < 2:
                        print("用法: prepare <image_path> <prompt> [model]")
                        print("示例: prepare test/lamp.webp '把灯变成蓝色' Fast")
                        continue

                    image_path = parts[0]
                    prompt_text = parts[1]
                    model_name = parts[2] if len(parts) > 2 else "Fast"

                    if model_name not in ["Pro", "Fast"]:
                        print("模型必须是 Pro 或 Fast")
                        continue

                    # 懒加载 enhanced editor
                    if editor is None:
                        from core.enhanced_editor import EnhancedGeminiImageEditor

                        enhanced_editor = EnhancedGeminiImageEditor.__new__(
                            EnhancedGeminiImageEditor
                        )
                        enhanced_editor.page = page
                        enhanced_editor.enable_logging = True
                        enhanced_editor.event_log = []
                    else:
                        from core.enhanced_editor import EnhancedGeminiImageEditor

                        if not isinstance(editor, EnhancedGeminiImageEditor):
                            enhanced_editor = EnhancedGeminiImageEditor.__new__(
                                EnhancedGeminiImageEditor
                            )
                            enhanced_editor.page = page
                            enhanced_editor.enable_logging = True
                            enhanced_editor.event_log = []
                        else:
                            enhanced_editor = editor

                    print("=" * 60)
                    print("测试准备阶段（不提交）")
                    print("=" * 60)
                    print(f"图片: {image_path}")
                    print(f"提示词: {prompt_text}")
                    print(f"模型: {model_name}")
                    print()

                    total_start = time.time()

                    try:
                        # 使用共享的 prepare_for_generation 方法
                        success = await enhanced_editor.prepare_for_generation(
                            input_image=image_path,
                            prompt=prompt_text,
                            model=model_name,
                            temporary_chat=False,
                        )

                        total_time = time.time() - total_start
                        print(f"\n总耗时: {total_time:.3f}s")
                        print("=" * 60)

                        if success:
                            print("✓ 准备完成（已就绪可提交）")
                        else:
                            print("❌ 准备失败")

                    except Exception as e:
                        print(f"\n❌ 准备过程出错: {e}")
                        import traceback

                        traceback.print_exc()

                elif cmd.startswith("generate "):
                    # 完整图片生成流程测试（对应 API /v1/images/edits）
                    # 语法: generate <image_path> <prompt> [model]
                    # 示例: generate tests/lamp.webp "把灯变成蓝色" Fast
                    try:
                        from io import BytesIO
                        from PIL import Image

                        parts = cmd[9:].strip().split(maxsplit=2)
                        if len(parts) < 2:
                            print("用法: generate <image_path> <prompt> [model]")
                            print("示例: generate tests/lamp.webp '把灯变成蓝色' Fast")
                            continue

                        image_path = parts[0]
                        prompt_text = parts[1]
                        model_name = parts[2] if len(parts) > 2 else "Fast"

                        if model_name not in ["Pro", "Fast"]:
                            print("模型必须是 Pro 或 Fast")
                            continue

                        # 懒加载 enhanced editor
                        from core.enhanced_editor import EnhancedGeminiImageEditor
                        if editor is None or not isinstance(editor, EnhancedGeminiImageEditor):
                            enhanced_editor = EnhancedGeminiImageEditor.__new__(
                                EnhancedGeminiImageEditor
                            )
                            enhanced_editor.page = page
                            enhanced_editor.enable_logging = True
                            enhanced_editor.event_log = []
                        else:
                            enhanced_editor = editor

                        print("=" * 60)
                        print("完整图片生成流程测试（对应 API /v1/images/edits）")
                        print("=" * 60)
                        print(f"图片: {image_path}")
                        print(f"提示词: {prompt_text}")
                        print(f"模型: {model_name}")
                        print()

                        total_start = time.time()
                        timings = {}

                        # ========== 阶段1: 准备环境 ==========
                        print("=== 阶段1: 准备环境 ===")
                        stage_start = time.time()
                        success = await enhanced_editor.prepare_for_generation(
                            input_image=image_path,
                            prompt=prompt_text,
                            model=model_name,
                            temporary_chat=False,
                        )
                        timings["prepare"] = time.time() - stage_start
                        print(f"  ⏱ [准备阶段] {timings['prepare']:.3f}s")

                        if not success:
                            print("❌ 准备失败")
                            continue

                        # ========== 阶段2: 提交生成 ==========
                        print("\n=== 阶段2: 提交生成 ===")
                        stage_start = time.time()
                        if not await enhanced_editor.submit_generation():
                            print("❌ 提交失败")
                            continue
                        timings["submit"] = time.time() - stage_start
                        print(f"  ⏱ [提交请求] {timings['submit']:.3f}s")

                        # ========== 阶段3: 等待生成 ==========
                        print("\n=== 阶段3: 等待生成 ===")
                        stage_start = time.time()
                        generation_success = await enhanced_editor.wait_for_generation(timeout=120)
                        timings["generation"] = time.time() - stage_start
                        print(f"  ⏱ [生成等待] {timings['generation']:.3f}s")

                        if not generation_success:
                            print("⚠ 生成超时，继续尝试下载...")

                        # ========== 阶段4: 快速下载预览图 ==========
                        print("\n=== 阶段4: 快速下载预览图 ===")
                        stage_start = time.time()

                        urls = await get_last_response_images(page)
                        if not urls:
                            print("❌ 未找到生成的图片")
                            continue

                        print(f"  找到 {len(urls)} 张图片")

                        # 下载所有预览图
                        images_info = []
                        date_str = datetime.now().strftime("%Y%m%d")
                        date_dir = output_dir / date_str
                        date_dir.mkdir(parents=True, exist_ok=True)

                        for i, url in enumerate(urls):
                            response = await page.request.get(url)
                            if not response.ok:
                                print(f"  [{i}] 下载失败: HTTP {response.status}")
                                continue

                            image_bytes = await response.body()
                            sha256_hash = hashlib.sha256(image_bytes).digest()
                            file_hash = base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")

                            fmt = detect_image_format(image_bytes)
                            preview_path = date_dir / f"{file_hash}.{fmt}"
                            with open(preview_path, "wb") as f:
                                f.write(image_bytes)

                            images_info.append({
                                "index": i,
                                "hash": file_hash,
                                "id": f"{date_str}/{file_hash}",
                                "date": date_str,
                                "format": fmt,
                                "url": url,
                                "size": len(image_bytes),
                            })
                            print(f"  [{i}] 预览图: {file_hash[:16]}... ({len(image_bytes)/1024:.1f}KB)")

                        timings["download"] = time.time() - stage_start
                        print(f"  ⏱ [预览下载] {timings['download']:.3f}s ({len(images_info)} 张)")

                        # ========== 阶段5: 高清下载（可选，测试第一张）==========
                        if images_info:
                            print("\n=== 阶段5: 高清下载（第一张）===")
                            stage_start = time.time()

                            first_img = images_info[0]
                            hd_bytes = await enhanced_editor._download_via_hover_button(first_img["url"], "no_wait")

                            if hd_bytes:
                                img = Image.open(BytesIO(hd_bytes))
                                width, height = img.size

                                webp_buffer = BytesIO()
                                img.save(webp_buffer, "WEBP", lossless=True)
                                webp_data = webp_buffer.getvalue()

                                hd_path = date_dir / f"{first_img['hash']}_hd.webp"
                                with open(hd_path, "wb") as f:
                                    f.write(webp_data)

                                timings["hd"] = time.time() - stage_start
                                print(f"  高清图: {hd_path}")
                                print(f"  尺寸: {width}x{height}, 大小: {len(webp_data)/1024:.1f}KB")
                                print(f"  ⏱ [高清下载] {timings['hd']:.3f}s")
                            else:
                                print("  ❌ 高清下载失败")
                                timings["hd"] = time.time() - stage_start

                        # ========== 总结 ==========
                        total_time = time.time() - total_start
                        print("\n" + "=" * 60)
                        print("生成流程测试完成")
                        print("=" * 60)
                        print(f"总耗时: {total_time:.3f}s")
                        print(f"  准备: {timings.get('prepare', 0):.3f}s")
                        print(f"  提交: {timings.get('submit', 0):.3f}s")
                        print(f"  生成: {timings.get('generation', 0):.3f}s")
                        print(f"  预览下载: {timings.get('download', 0):.3f}s")
                        print(f"  高清下载: {timings.get('hd', 0):.3f}s")
                        print()
                        print("预览图路径（API 响应格式）:")
                        for img in images_info:
                            print(f"  {img['id']}")

                        # 保存到缓存供后续 hd 命令使用
                        if not hasattr(main, "preview_cache"):
                            main.preview_cache = {}
                        for img in images_info:
                            cache_key = f"{img['date']}/{img['hash']}"
                            main.preview_cache[cache_key] = {
                                "url": img["url"],
                                "index": img["index"],
                                "path": str(date_dir / f"{img['hash']}.{img['format']}"),
                            }

                    except ValueError as e:
                        print(f"参数错误: {e}")
                        print("用法: generate <image_path> <prompt> [model]")
                    except ImportError:
                        print("❌ 需要安装 Pillow: pip install Pillow")
                    except Exception as e:
                        print(f"❌ 生成过程出错: {e}")
                        import traceback
                        traceback.print_exc()

                elif cmd == "bench":
                    # 性能对比测试：测试不同点击方法的性能
                    urls = await get_last_response_images(page)

                    if not urls:
                        print("最后一轮对话中未找到可下载的图片")
                        continue

                    # 懒加载 editor
                    if editor is None:
                        from core.image_editor import GeminiImageEditor

                        editor = GeminiImageEditor.__new__(GeminiImageEditor)
                        editor.page = page

                    url = urls[0]  # 使用第一张图片
                    methods = ["js", "force", "no_wait", "normal"]

                    print("=" * 60)
                    print("下载性能对比测试")
                    print("=" * 60)
                    print(f"测试图片: {url[:80]}...")
                    print()

                    results = []

                    for method in methods:
                        print(f"测试点击方法: {method}")
                        save_path = output_dir / f"bench_{method}.webp"

                        start = time.time()
                        success = await editor.download_image_as_webp(
                            url, str(save_path), click_method=method
                        )
                        elapsed = time.time() - start

                        if success:
                            results.append((method, elapsed))
                            print(f"  ✓ 完成，总耗时: {elapsed:.3f}s")
                        else:
                            print("  ❌ 失败")

                        print()
                        await asyncio.sleep(1)  # 短暂等待避免触发限制

                    # 显示对比结果
                    if results:
                        print("=" * 60)
                        print("性能对比结果")
                        print("=" * 60)
                        results.sort(key=lambda x: x[1])  # 按耗时排序
                        for i, (method, elapsed) in enumerate(results, 1):
                            print(f"  {i}. {method:10s} - {elapsed:.3f}s")
                        print()
                        fastest = results[0]
                        print(f"最快方法: {fastest[0]} ({fastest[1]:.3f}s)")

                elif cmd == "shot" or cmd.startswith("shot "):
                    # 截取当前页面截图
                    parts = cmd.split(maxsplit=1)
                    if len(parts) > 1:
                        name = parts[1]
                    else:
                        name = datetime.now().strftime("%Y%m%d_%H%M%S")

                    # 先截取 PNG，然后转换为 WebP
                    from io import BytesIO
                    from PIL import Image

                    png_data = await page.screenshot(full_page=True)
                    img = Image.open(BytesIO(png_data))

                    screenshot_path = output_dir / f"screenshot_{name}.webp"
                    img.save(screenshot_path, "WEBP", quality=50)
                    print(f"✅ 截图已保存: {screenshot_path}")

                elif cmd == "url":
                    print(f"当前URL: {page.url}")

                elif cmd.startswith("goto "):
                    target_url = cmd[5:].strip()
                    print(f"正在跳转到: {target_url}")
                    await page.goto(target_url)
                    print(f"✅ 已跳转，当前URL: {page.url}")

                elif cmd.startswith("scroll "):
                    # 滚动页面
                    parts = cmd.split()
                    if len(parts) < 2:
                        print("用法: scroll <down|up|top|bottom|<pixels>>")
                        print("  down   - 向下滚动一屏")
                        print("  up     - 向上滚动一屏")
                        print("  top    - 滚动到顶部")
                        print("  bottom - 滚动到底部")
                        print("  <pixels> - 滚动指定像素（正数向下，负数向上）")
                        continue

                    action = parts[1]

                    if action == "down":
                        # 向下滚动一屏
                        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                        print("✅ 向下滚动一屏")
                    elif action == "up":
                        # 向上滚动一屏
                        await page.evaluate("window.scrollBy(0, -window.innerHeight * 0.8)")
                        print("✅ 向上滚动一屏")
                    elif action == "top":
                        # 滚动到顶部
                        await page.evaluate("window.scrollTo(0, 0)")
                        print("✅ 滚动到顶部")
                    elif action == "bottom":
                        # 滚动到底部
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        print("✅ 滚动到底部")
                    else:
                        # 滚动指定像素
                        try:
                            pixels = int(action)
                            await page.evaluate(f"window.scrollBy(0, {pixels})")
                            direction = "向下" if pixels > 0 else "向上"
                            print(f"✅ {direction}滚动 {abs(pixels)} 像素")
                        except ValueError:
                            print(f"错误: 未知的滚动操作 '{action}'")

                    # 等待滚动完成
                    await asyncio.sleep(0.3)

                elif cmd.startswith("move "):
                    # 拟人鼠标移动并截图（自动吸附到最近按钮中心）
                    parts = cmd.split()
                    if len(parts) < 3:
                        print("用法: move <x> <y> [name]")
                        print("  移动后会自动吸附到最近按钮中心（带随机偏移）")
                        continue

                    try:
                        target_x = int(parts[1])
                        target_y = int(parts[2])
                        name = (
                            parts[3]
                            if len(parts) > 3
                            else datetime.now().strftime("%Y%m%d_%H%M%S")
                        )
                    except ValueError:
                        print("错误: x 和 y 必须是整数")
                        continue

                    # 获取当前鼠标位置（从页面中心开始，如果是第一次移动）
                    try:
                        current_pos = await page.evaluate(
                            "() => window.__mousePos || {x: window.innerWidth/2, y: window.innerHeight/2}"
                        )
                        start_x, start_y = current_pos["x"], current_pos["y"]
                    except Exception:
                        viewport = page.viewport_size
                        start_x = viewport["width"] // 2 if viewport else 640
                        start_y = viewport["height"] // 2 if viewport else 360

                    # 查找最近的可见按钮并计算吸附位置
                    snap_info = await page.evaluate(
                        """([targetX, targetY]) => {
                        const buttons = document.querySelectorAll('button');
                        let nearest = null;
                        let minDist = Infinity;

                        for (const btn of buttons) {
                            if (!btn.offsetParent) continue;  // 跳过隐藏的按钮
                            const rect = btn.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) continue;

                            const centerX = rect.left + rect.width / 2;
                            const centerY = rect.top + rect.height / 2;
                            const dist = Math.sqrt((centerX - targetX) ** 2 + (centerY - targetY) ** 2);

                            if (dist < minDist) {
                                minDist = dist;
                                nearest = {
                                    centerX: centerX,
                                    centerY: centerY,
                                    width: rect.width,
                                    height: rect.height,
                                    dist: dist,
                                    aria: btn.getAttribute('aria-label') || '',
                                    text: (btn.textContent || '').trim().substring(0, 30)
                                };
                            }
                        }
                        return nearest;
                    }""",
                        [target_x, target_y],
                    )

                    # 计算最终目标位置（吸附到按钮中心 + 随机偏移）
                    final_x, final_y = target_x, target_y
                    snapped = False

                    if snap_info and snap_info["dist"] < 100:  # 100px 范围内吸附
                        # 在按钮中心附近添加随机偏移（按钮尺寸的 10-20%）
                        offset_range_x = max(3, snap_info["width"] * 0.15)
                        offset_range_y = max(3, snap_info["height"] * 0.15)
                        offset_x = random.uniform(-offset_range_x, offset_range_x)
                        offset_y = random.uniform(-offset_range_y, offset_range_y)

                        final_x = int(snap_info["centerX"] + offset_x)
                        final_y = int(snap_info["centerY"] + offset_y)
                        snapped = True

                        btn_label = snap_info["aria"] or snap_info["text"] or "(无标签)"
                        print(
                            f"检测到最近按钮: '{btn_label}' (距离 {snap_info['dist']:.0f}px)"
                        )
                        print(
                            f"吸附到按钮中心: ({snap_info['centerX']:.0f}, {snap_info['centerY']:.0f}) + 偏移 ({offset_x:.1f}, {offset_y:.1f})"
                        )

                    # 生成拟人轨迹
                    path = generate_human_path(start_x, start_y, final_x, final_y)
                    print(
                        f"移动鼠标: ({start_x}, {start_y}) -> ({final_x}, {final_y}), {len(path)} 步"
                    )

                    # 逐步移动鼠标
                    for x, y in path:
                        await page.mouse.move(x, y)
                        delay = random.uniform(0.01, 0.03)
                        await asyncio.sleep(delay)

                    # 记录鼠标位置
                    await page.evaluate(
                        f"() => window.__mousePos = {{x: {final_x}, y: {final_y}}}"
                    )

                    # 截图并绘制轨迹
                    import io

                    from PIL import Image, ImageDraw

                    png_data = await page.screenshot()
                    img = Image.open(io.BytesIO(png_data))
                    draw = ImageDraw.Draw(img)

                    # 绘制轨迹线（红色）
                    for i in range(len(path) - 1):
                        draw.line([path[i], path[i + 1]], fill=(255, 0, 0), width=2)

                    # 绘制起点（绿色）
                    r = 5
                    draw.ellipse(
                        [
                            path[0][0] - r,
                            path[0][1] - r,
                            path[0][0] + r,
                            path[0][1] + r,
                        ],
                        fill=(0, 255, 0),
                    )

                    # 绘制终点
                    if snapped:
                        # 吸附时：绘制按钮中心（黄色）和实际位置（蓝色）
                        btn_cx, btn_cy = int(snap_info["centerX"]), int(snap_info["centerY"])
                        draw.ellipse(
                            [btn_cx - r, btn_cy - r, btn_cx + r, btn_cy + r],
                            fill=(255, 255, 0),  # 黄色 = 按钮中心
                        )
                        draw.ellipse(
                            [final_x - r, final_y - r, final_x + r, final_y + r],
                            fill=(0, 0, 255),  # 蓝色 = 实际位置
                        )
                    else:
                        # 未吸附：只绘制终点（蓝色）
                        draw.ellipse(
                            [
                                path[-1][0] - r,
                                path[-1][1] - r,
                                path[-1][0] + r,
                                path[-1][1] + r,
                            ],
                            fill=(0, 0, 255),
                        )

                    # 保存为 webp
                    webp_path = output_dir / f"move_{name}.webp"
                    img.save(webp_path, "WEBP", quality=50)

                    print(f"✅ 移动完成，轨迹截图已保存: {webp_path}")

                elif cmd.startswith("click "):
                    # 鼠标点击并截图（自动吸附到最近按钮中心）
                    parts = cmd.split()
                    if len(parts) < 3:
                        print("用法: click <x> <y> [name]")
                        print("  先计算吸附位置，再拟人移动并点击")
                        continue

                    try:
                        target_x = int(parts[1])
                        target_y = int(parts[2])
                        name = (
                            parts[3]
                            if len(parts) > 3
                            else datetime.now().strftime("%Y%m%d_%H%M%S")
                        )
                    except ValueError:
                        print("错误: x 和 y 必须是整数")
                        continue

                    # 获取当前鼠标位置
                    try:
                        current_pos = await page.evaluate(
                            "() => window.__mousePos || {x: window.innerWidth/2, y: window.innerHeight/2}"
                        )
                        start_x, start_y = current_pos["x"], current_pos["y"]
                    except Exception:
                        viewport = page.viewport_size
                        start_x = viewport["width"] // 2 if viewport else 640
                        start_y = viewport["height"] // 2 if viewport else 360

                    # 查找最近的可见按钮并计算吸附位置
                    snap_info = await page.evaluate(
                        """([targetX, targetY]) => {
                        const buttons = document.querySelectorAll('button');
                        let nearest = null;
                        let minDist = Infinity;

                        for (const btn of buttons) {
                            if (!btn.offsetParent) continue;
                            const rect = btn.getBoundingClientRect();
                            if (rect.width === 0 || rect.height === 0) continue;

                            const centerX = rect.left + rect.width / 2;
                            const centerY = rect.top + rect.height / 2;
                            const dist = Math.sqrt((centerX - targetX) ** 2 + (centerY - targetY) ** 2);

                            if (dist < minDist) {
                                minDist = dist;
                                nearest = {
                                    centerX: centerX,
                                    centerY: centerY,
                                    width: rect.width,
                                    height: rect.height,
                                    dist: dist,
                                    aria: btn.getAttribute('aria-label') || '',
                                    text: (btn.textContent || '').trim().substring(0, 30)
                                };
                            }
                        }
                        return nearest;
                    }""",
                        [target_x, target_y],
                    )

                    # 计算最终目标位置（吸附到按钮中心 + 随机偏移）
                    final_x, final_y = target_x, target_y
                    snapped = False

                    if snap_info and snap_info["dist"] < 100:
                        offset_range_x = max(3, snap_info["width"] * 0.15)
                        offset_range_y = max(3, snap_info["height"] * 0.15)
                        offset_x = random.uniform(-offset_range_x, offset_range_x)
                        offset_y = random.uniform(-offset_range_y, offset_range_y)

                        final_x = int(snap_info["centerX"] + offset_x)
                        final_y = int(snap_info["centerY"] + offset_y)
                        snapped = True

                        btn_label = snap_info["aria"] or snap_info["text"] or "(无标签)"
                        print(
                            f"检测到最近按钮: '{btn_label}' (距离 {snap_info['dist']:.0f}px)"
                        )
                        print(
                            f"吸附到按钮中心: ({snap_info['centerX']:.0f}, {snap_info['centerY']:.0f}) + 偏移 ({offset_x:.1f}, {offset_y:.1f})"
                        )

                    # 生成拟人轨迹并移动
                    path = generate_human_path(start_x, start_y, final_x, final_y)
                    print(
                        f"移动鼠标: ({start_x}, {start_y}) -> ({final_x}, {final_y}), {len(path)} 步"
                    )

                    for x, y in path:
                        await page.mouse.move(x, y)
                        delay = random.uniform(0.01, 0.03)
                        await asyncio.sleep(delay)

                    # 记录鼠标位置
                    await page.evaluate(
                        f"() => window.__mousePos = {{x: {final_x}, y: {final_y}}}"
                    )

                    # 执行点击
                    print(f"点击位置: ({final_x}, {final_y})")
                    await page.mouse.click(final_x, final_y)

                    # 等待页面响应
                    await asyncio.sleep(0.5)

                    # 截图并绘制轨迹和点击位置
                    import io

                    from PIL import Image, ImageDraw

                    png_data = await page.screenshot()
                    img = Image.open(io.BytesIO(png_data))
                    draw = ImageDraw.Draw(img)

                    # 绘制轨迹线（红色）
                    for i in range(len(path) - 1):
                        draw.line([path[i], path[i + 1]], fill=(255, 0, 0), width=2)

                    # 绘制起点（绿色）
                    r = 5
                    draw.ellipse(
                        [
                            path[0][0] - r,
                            path[0][1] - r,
                            path[0][0] + r,
                            path[0][1] + r,
                        ],
                        fill=(0, 255, 0),
                    )

                    # 绘制点击位置（蓝色圆圈 + 十字）
                    click_r = 10
                    draw.ellipse(
                        [
                            final_x - click_r,
                            final_y - click_r,
                            final_x + click_r,
                            final_y + click_r,
                        ],
                        outline=(0, 0, 255),
                        width=3,
                    )
                    # 十字标记
                    cross_size = 15
                    draw.line(
                        [final_x - cross_size, final_y, final_x + cross_size, final_y],
                        fill=(0, 0, 255),
                        width=2,
                    )
                    draw.line(
                        [final_x, final_y - cross_size, final_x, final_y + cross_size],
                        fill=(0, 0, 255),
                        width=2,
                    )

                    # 如果吸附了，额外绘制按钮中心（黄色）
                    if snapped:
                        btn_cx, btn_cy = int(snap_info["centerX"]), int(snap_info["centerY"])
                        r = 5
                        draw.ellipse(
                            [btn_cx - r, btn_cy - r, btn_cx + r, btn_cy + r],
                            fill=(255, 255, 0),
                        )

                    # 保存为 webp
                    webp_path = output_dir / f"click_{name}.webp"
                    img.save(webp_path, "WEBP", quality=50)

                    print(f"✅ 点击完成，截图已保存: {webp_path}")

                elif cmd == "help":
                    print("命令:")
                    print("  pause        - 打开 Playwright Inspector")
                    print("  buttons      - 列出所有按钮")
                    print("  images       - 列出最后一轮对话中的图片")
                    print("  fetch <n>    - 使用 page.request.get 下载第n张图片")
                    print(
                        "  webp <n> [method] - 使用 download_image_as_webp 下载第n张 (hover优先)"
                    )
                    print("                      method: js|force|no_wait|normal (默认js)")
                    print("  download     - 使用 request API 下载所有图片")
                    print("  webp_all     - 使用 download_image_as_webp 下载所有图片")
                    print("  bench        - 性能对比测试（对比不同点击方法）")
                    print()
                    print("  === 完整生成流程（对应 API）===")
                    print("  generate <image> <prompt> [model] - 完整生成流程（对应 /v1/images/edits）")
                    print()
                    print("  === 预览/高清分离测试 ===")
                    print("  preview <n>  - 快速下载预览图，返回 {日期}/{hash} 参数")
                    print("  hd <date>/<hash> - 根据预览参数下载高清图")
                    print("  flow <n>     - 完整流程测试（预览→高清）")
                    print()
                    print("  === 页面操作 ===")
                    print("  shot [name]  - 截取当前页面截图")
                    print("  url          - 显示当前页面URL")
                    print("  goto <url>   - 跳转到指定URL")
                    print("  scroll <action> - 滚动页面 (down/up/top/bottom/<pixels>)")
                    print("  move <x> <y> [name] - 拟人鼠标移动并截图(webp)")
                    print("  click <x> <y> [name] - 拟人鼠标移动+点击并截图(webp)")
                    print()
                    print("  === 其他 ===")
                    print("  model <Pro|Fast> - 测试模型切换功能")
                    print("  env [Pro|Fast] - 测试页面环境准备（开启新对话+模型+激活）")
                    print("  prepare <image> <prompt> [model] - 测试准备阶段（环境+图片+文本）")
                    print("  quit         - 退出")

                else:
                    print("未知命令，输入 'help' 查看帮助")

            except KeyboardInterrupt:
                print("\n退出...")
                break
            except Exception as e:
                print(f"错误: {e}")
                import traceback

                traceback.print_exc()

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
