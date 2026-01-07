"""
测试 Playwright 下载图片

使用方法：
    python test/codegen_persistent.py

这会使用已登录的浏览器数据，提供交互式命令测试下载功能。
"""

import asyncio
import base64
import hashlib
import os
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
    # 配置
    test_url = "https://gemini.google.com/app/07ac44601b8aed18#8f313e887254b0d5"
    user_data_dir = Path(__file__).parent.parent / "data" / "browser_data" / "0"
    output_dir = Path(__file__).parent.parent / "data" / "test_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Playwright 下载测试")
    print("=" * 60)
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
