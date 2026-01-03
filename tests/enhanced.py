"""
测试增强版图片编辑器的各项功能
"""

import asyncio
from pathlib import Path

from core.enhanced_editor import EnhancedGeminiImageEditor


async def test_model_selection():
    """测试模型选择功能"""
    print("=" * 60)
    print("测试1: 模型选择功能")
    print("=" * 60)

    editor = EnhancedGeminiImageEditor(account_id=0, headless=False)

    try:
        await editor.launch()

        # 测试切换到 Pro
        print("\n--- 测试切换到 Pro ---")
        await editor.ensure_model_selection("Pro")
        await asyncio.sleep(2)

        # 测试切换到 Fast
        print("\n--- 测试切换到 Fast ---")
        await editor.ensure_model_selection("Fast")
        await asyncio.sleep(2)

        print("\n✓ 模型选择测试完成")

    finally:
        await editor.close()


async def test_temporary_chat():
    """测试临时对话功能"""
    print("\n" + "=" * 60)
    print("测试2: 临时对话功能")
    print("=" * 60)

    editor = EnhancedGeminiImageEditor(account_id=0, headless=False)

    try:
        await editor.launch()

        # 启用临时对话
        await editor.enable_temporary_chat()

        print("\n浏览器将保持打开10秒，请检查是否进入临时对话模式...")
        await asyncio.sleep(10)

        print("\n✓ 临时对话测试完成")

    finally:
        await editor.close()


async def test_stable_image_activation():
    """测试稳定的图片生成激活"""
    print("\n" + "=" * 60)
    print("测试3: 稳定的图片生成激活")
    print("=" * 60)

    editor = EnhancedGeminiImageEditor(account_id=0, headless=False)

    try:
        await editor.launch()

        # 激活图片生成功能
        await editor.activate_image_generation_stable()

        print("\n浏览器将保持打开10秒，请检查是否成功激活图片生成...")
        await asyncio.sleep(10)

        print("\n✓ 图片生成激活测试完成")

    finally:
        await editor.close()


async def test_full_workflow():
    """测试完整的工作流程"""
    print("\n" + "=" * 60)
    print("测试4: 完整工作流程（带事件日志）")
    print("=" * 60)

    test_image = Path(__file__).parent / "test" / "lamp.webp"

    if not test_image.exists():
        print(f"\n❌ 测试图片不存在: {test_image}")
        return

    editor = EnhancedGeminiImageEditor(
        account_id=0, headless=False, enable_logging=True  # 启用事件日志
    )

    try:
        await editor.launch()

        # 执行完整的编辑流程
        result_paths = await editor.edit_image_enhanced(
            input_image=str(test_image),
            prompt="把这个灯变成红色的",
            output_dir="output/test_enhanced",
            wait_time=30,
            model="Fast",
            temporary_chat=False,
            output_format="webp",
            webp_lossless=True,
            save_log=True,
        )

        if result_paths:
            print("\n" + "=" * 60)
            print("✅ 完整工作流程测试成功！")
            print("=" * 60)
            print(f"\n生成了 {len(result_paths)} 张图片:")
            for path in result_paths:
                print(f"  - {path}")

            print("\n事件日志已保存到: output/test_enhanced/event_log.json")
        else:
            print("\n❌ 完整工作流程测试失败")

    finally:
        await editor.close()


async def test_temporary_chat_workflow():
    """测试临时对话 + 图片编辑工作流程"""
    print("\n" + "=" * 60)
    print("测试5: 临时对话 + 图片编辑")
    print("=" * 60)

    test_image = Path(__file__).parent / "test" / "lamp.webp"

    if not test_image.exists():
        print(f"\n❌ 测试图片不存在: {test_image}")
        return

    editor = EnhancedGeminiImageEditor(
        account_id=0, headless=False, enable_logging=True
    )

    try:
        await editor.launch()

        # 使用临时对话模式编辑图片
        result_paths = await editor.edit_image_enhanced(
            input_image=str(test_image),
            prompt="把这个灯变成绿色的",
            output_dir="output/test_temporary",
            wait_time=30,
            model="Fast",
            temporary_chat=True,  # 使用临时对话
            output_format="webp",
            webp_lossless=True,
            save_log=True,
        )

        if result_paths:
            print("\n✅ 临时对话工作流程测试成功！")
        else:
            print("\n❌ 临时对话工作流程测试失败")

    finally:
        await editor.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        test_name = sys.argv[1]

        if test_name == "model":
            asyncio.run(test_model_selection())
        elif test_name == "temp_chat":
            asyncio.run(test_temporary_chat())
        elif test_name == "activate":
            asyncio.run(test_stable_image_activation())
        elif test_name == "full":
            asyncio.run(test_full_workflow())
        elif test_name == "temp_workflow":
            asyncio.run(test_temporary_chat_workflow())
        else:
            print(f"未知测试: {test_name}")
            print("\n可用的测试:")
            print("  model          - 测试模型选择")
            print("  temp_chat      - 测试临时对话")
            print("  activate       - 测试图片生成激活")
            print("  full           - 测试完整工作流程")
            print("  temp_workflow  - 测试临时对话+编辑")
    else:
        # 运行所有测试
        print("运行所有测试...\n")
        asyncio.run(test_model_selection())
        asyncio.run(test_temporary_chat())
        asyncio.run(test_stable_image_activation())
        asyncio.run(test_full_workflow())
        asyncio.run(test_temporary_chat_workflow())
        print("\n✓ 所有测试完成")
