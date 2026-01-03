"""
测试 Playwright 下载图片

使用方法：
    python test/codegen_persistent.py

这会使用已登录的浏览器数据，提供交互式命令测试下载功能。
"""

import asyncio
import sys
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
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
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

                elif cmd.startswith("webp "):
                    # 使用 download_image_as_webp 测试（先 hover 下载按钮，再回退到 request）
                    try:
                        index = int(cmd[5:])
                        urls = await get_last_response_images(page)

                        if index >= len(urls):
                            print(f"索引 {index} 超出范围（共 {len(urls)} 张）")
                            continue

                        url = urls[index]
                        print(f"正在下载图片 [{index}] (download_image_as_webp)...")
                        print(f"  URL: {url[:80]}...")

                        # 懒加载 editor
                        if editor is None:
                            from core.image_editor import GeminiImageEditor

                            editor = GeminiImageEditor.__new__(GeminiImageEditor)
                            editor.page = page

                        save_path = output_dir / f"webp_{index}.webp"
                        success = await editor.download_image_as_webp(
                            url, str(save_path)
                        )

                        if success:
                            print("✓ WebP 下载测试完成")
                        else:
                            print("❌ WebP 下载失败")

                    except ValueError:
                        print("用法: webp <index>")

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

                elif cmd == "help":
                    print("命令:")
                    print("  pause        - 打开 Playwright Inspector")
                    print("  buttons      - 列出所有按钮")
                    print("  images       - 列出最后一轮对话中的图片")
                    print("  fetch <n>    - 使用 page.request.get 下载第n张图片")
                    print(
                        "  webp <n>     - 使用 download_image_as_webp 下载第n张 (hover优先)"
                    )
                    print("  download     - 使用 request API 下载所有图片")
                    print("  webp_all     - 使用 download_image_as_webp 下载所有图片")
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
