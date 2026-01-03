"""
Gemini Browser 使用示例
"""

import asyncio
from gemini_browser import GeminiBrowser


async def example_basic():
    """基础示例：启动浏览器并访问Gemini"""
    print("=== 基础示例 ===")
    browser = GeminiBrowser(account_id=0, headless=False)

    try:
        # 启动浏览器
        page = await browser.launch()

        # 获取页面信息
        title = await page.title()
        url = page.url
        print(f"页面标题: {title}")
        print(f"当前URL: {url}")

        # 等待5秒
        await asyncio.sleep(5)

    finally:
        await browser.close()


async def example_headless():
    """无头模式示例"""
    print("\n=== 无头模式示例 ===")
    browser = GeminiBrowser(account_id=0, headless=True)

    try:
        page = await browser.launch()
        print(f"✓ 无头模式启动成功: {page.url}")
        await asyncio.sleep(3)

    finally:
        await browser.close()


async def example_multi_account():
    """多账户示例"""
    print("\n=== 多账户示例 ===")

    # 使用账户0
    print("使用账户0...")
    browser0 = GeminiBrowser(account_id=0, headless=True)
    try:
        page0 = await browser0.launch()
        print(f"✓ 账户0: {page0.url}")
        await asyncio.sleep(2)
    finally:
        await browser0.close()

    # 使用账户1（如果存在）
    print("\n使用账户1...")
    browser1 = GeminiBrowser(account_id=1, headless=True)
    try:
        page1 = await browser1.launch()
        print(f"✓ 账户1: {page1.url}")
        await asyncio.sleep(2)
    except RuntimeError as e:
        print(f"⚠ 账户1未初始化: {e}")
    finally:
        await browser1.close()


async def example_custom_operations():
    """自定义操作示例"""
    print("\n=== 自定义操作示例 ===")
    browser = GeminiBrowser(account_id=0, headless=False)

    try:
        page = await browser.launch()

        # 你可以在这里进行自定义操作
        # 例如：等待特定元素、点击按钮、输入文本等

        # 示例：获取页面内容
        content = await page.content()
        print(f"✓ 页面内容长度: {len(content)} 字符")

        # 示例：截图
        from pathlib import Path
        screenshot_path = Path(__file__).parent / "test" / "example_screenshot.png"
        screenshot_path.parent.mkdir(exist_ok=True)
        await page.screenshot(path=str(screenshot_path))
        print(f"✓ 截图保存: {screenshot_path}")

        await asyncio.sleep(3)

    finally:
        await browser.close()


if __name__ == "__main__":
    import sys

    print("Gemini Browser 使用示例")
    print("=" * 60)

    if len(sys.argv) > 1:
        example = sys.argv[1]

        if example == "basic":
            asyncio.run(example_basic())
        elif example == "headless":
            asyncio.run(example_headless())
        elif example == "multi":
            asyncio.run(example_multi_account())
        elif example == "custom":
            asyncio.run(example_custom_operations())
        else:
            print(f"未知示例: {example}")
            sys.exit(1)
    else:
        # 运行所有示例
        print("运行所有示例...\n")
        asyncio.run(example_basic())
        asyncio.run(example_headless())
        asyncio.run(example_multi_account())
        asyncio.run(example_custom_operations())

    print("\n✓ 所有示例运行完成")
