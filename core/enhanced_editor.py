"""
增强版 Gemini 图片编辑器 - 支持更智能的页面适配和模型选择

新增功能：
1. 事件监听和日志记录
2. 智能模型选择（Pro/Fast）
3. 临时会话支持
4. 不依赖文本标签的稳定工具选择
5. 自动处理页面语言变化
"""

import asyncio
import json
from pathlib import Path
from typing import Literal, Optional

from .image_editor import GeminiImageEditor


class EnhancedGeminiImageEditor(GeminiImageEditor):
    """增强版图片编辑器"""

    def __init__(
        self,
        account_id: int = 0,
        headless: bool = False,
        proxy: Optional[str] = None,
        enable_logging: bool = True,
        user_data_dir: Optional[Path] = None,
    ):
        super().__init__(account_id, headless, proxy, user_data_dir)
        self.enable_logging = enable_logging
        self.event_log = []  # 事件日志

    async def launch(self, timeout: int = 60000):
        """启动浏览器并设置事件监听"""
        page = await super().launch(timeout)

        if self.enable_logging:
            await self._setup_event_listeners()

        return page

    async def _setup_event_listeners(self):
        """设置页面事件监听"""
        print("\n设置事件监听...")

        # 监听控制台消息
        self.page.on(
            "console",
            lambda msg: self._log_event(
                "console",
                {
                    "type": msg.type,
                    "text": msg.text,
                },
            ),
        )

        # 监听页面导航
        self.page.on(
            "framenavigated",
            lambda frame: self._log_event(
                "navigation",
                {
                    "url": frame.url,
                },
            ),
        )

        # 监听请求（可选，用于调试）
        # self.page.on("request", lambda req: self._log_event("request", {
        #     "url": req.url,
        #     "method": req.method,
        # }))

        print("✓ 事件监听已设置")

    def _log_event(self, event_type: str, data: dict):
        """记录事件"""
        import datetime

        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "type": event_type,
            "data": data,
        }
        self.event_log.append(log_entry)

        if self.enable_logging:
            print(
                f"[EVENT] {event_type}: {data.get('text', data.get('url', ''))[:100]}"
            )

    def save_event_log(self, path: str):
        """保存事件日志到文件"""
        log_file = Path(path)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(self.event_log, f, indent=2, ensure_ascii=False)

        print(f"✓ 事件日志已保存: {log_file}")

    async def ensure_model_selection(
        self, model: Literal["Pro", "Fast"] = "Fast"
    ) -> bool:
        """
        确保选择了指定的模型（Pro 或 Fast）

        方法：
        1. 检查当前模型
        2. 如果需要切换，点击模型选择按钮打开菜单
        3. 点击目标模型选项
        4. 验证切换结果

        注意：基于 Playwright Codegen 生成的代码
        - 点击 [data-test-id="bard-mode-menu-button"] 打开菜单
        - 点击 [data-test-id="bard-mode-option-快速"] 或 [data-test-id="bard-mode-option-pro"] 选择模型

        Args:
            model: 目标模型 "Pro" 或 "Fast"

        Returns:
            是否成功选择模型
        """
        print(f"\n确保模型选择为: {model}")

        try:
            # 查找模型选择按钮（基于 Codegen）
            menu_button_selector = '[data-test-id="bard-mode-menu-button"]'

            # 等待按钮出现（注意：按钮可能有 hidden class，但仍然可以交互）
            # 使用 state="attached" 而不是 "visible"
            await self.page.wait_for_selector(
                menu_button_selector, timeout=5000, state="attached"
            )

            # 获取当前显示的模型
            menu_button = self.page.locator(menu_button_selector)

            # 获取按钮内的文本来判断当前模型
            button_text = await menu_button.inner_text()
            print(f"  当前模型显示: '{button_text}'")

            # 判断当前是哪个模型
            is_currently_fast = (
                "Fast" in button_text
                or "快速" in button_text
                or "fast" in button_text.lower()
            )
            is_currently_pro = "Pro" in button_text or "pro" in button_text.lower()

            # 判断是否已经是目标模型
            if model == "Fast" and is_currently_fast:
                print("✓ 已经是 Fast 模型")
                return True
            elif model == "Pro" and is_currently_pro:
                print("✓ 已经是 Pro 模型")
                return True

            # 需要切换模型
            print(f"  切换到 {model} 模型...")

            # 步骤1: 点击菜单按钮打开下拉菜单
            await menu_button.click()
            print("  ✓ 已点击菜单按钮，等待菜单展开...")
            await asyncio.sleep(0.5)

            # 步骤2: 点击目标模型选项
            if model == "Fast":
                # 尝试中文和英文选择器
                option_selectors = [
                    '[data-test-id="bard-mode-option-快速"]',
                    '[data-test-id="bard-mode-option-fast"]',
                    '[data-test-id="bard-mode-option-Flash"]',  # 可能也叫 Flash
                ]
            else:  # Pro
                option_selectors = [
                    '[data-test-id="bard-mode-option-pro"]',
                    '[data-test-id="bard-mode-option-Pro"]',
                ]

            clicked = False
            for selector in option_selectors:
                try:
                    option = await self.page.wait_for_selector(
                        selector, timeout=2000, state="visible"
                    )
                    if option:
                        print(f"  ✓ 找到选项（选择器: {selector}）")
                        await option.click()
                        clicked = True
                        break
                except Exception:
                    continue

            # 如果基于 data-test-id 的选择器失败，尝试通过文本内容匹配
            if not clicked:
                print(f"  data-test-id 选择器未找到，尝试通过文本内容匹配...")
                try:
                    # 获取所有可见的按钮或可点击元素
                    all_buttons = await self.page.query_selector_all("button, [role='menuitem']")

                    target_texts = []
                    if model == "Fast":
                        target_texts = ["Fast", "快速", "Flash", "2.0 Flash"]
                    else:  # Pro
                        target_texts = ["Pro", "1.5 Pro"]

                    for button in all_buttons:
                        try:
                            # 检查按钮是否可见
                            is_visible = await button.is_visible()
                            if not is_visible:
                                continue

                            # 获取按钮文本
                            text = await button.text_content()
                            if not text:
                                continue

                            text = text.strip()

                            # 检查是否匹配目标文本
                            for target in target_texts:
                                if target in text:
                                    print(f"  ✓ 通过文本找到选项: '{text}'")
                                    await button.click()
                                    clicked = True
                                    break

                            if clicked:
                                break
                        except Exception:
                            continue

                except Exception as e:
                    print(f"  文本匹配过程出错: {e}")

            if not clicked:
                print(f"  ❌ 未找到 {model} 模型选项")
                return False

            # 等待切换完成
            await asyncio.sleep(1)

            # 验证切换结果
            new_button_text = await menu_button.inner_text()
            print(f"  切换后模型显示: '{new_button_text}'")

            # 判断切换后是哪个模型
            is_now_fast = (
                "Fast" in new_button_text
                or "快速" in new_button_text
                or "fast" in new_button_text.lower()
            )
            is_now_pro = "Pro" in new_button_text or "pro" in new_button_text.lower()

            if (model == "Fast" and is_now_fast) or (model == "Pro" and is_now_pro):
                print(f"✓ 成功切换到 {model} 模型")
                return True
            else:
                print(f"⚠ 切换后仍然是其他模型")
                return False

        except Exception as e:
            print(f"❌ 模型选择失败: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def enable_temporary_chat(self) -> bool:
        """
        启用临时对话模式

        步骤：
        1. 检查并展开左侧菜单（如果需要）
        2. 点击 "Temporary chat"/"临时对话" 按钮

        Returns:
            是否成功启用临时对话
        """
        print("\n启用临时对话模式...")

        try:
            # 步骤1: 确保左侧菜单展开
            print("  检查左侧菜单状态...")

            # 查找主菜单按钮（侧边栏未展开时显示）
            # 基于真实DOM: button.main-menu-button[aria-label="主菜单"]
            menu_button_selectors = [
                "button.main-menu-button",
                'button[data-test-id="side-nav-menu-button"]',
                'button[aria-label="主菜单"]',
                'button[aria-label="Main menu"]',
                'button[aria-label*="展开菜单"]',
                'button[aria-label*="Expand menu"]',
                'button mat-icon[fonticon="menu"]',
            ]

            menu_expanded = False
            for selector in menu_button_selectors:
                try:
                    menu_button = await self.page.query_selector(selector)
                    if menu_button:
                        # 检查按钮是否可见（如果侧边栏已展开，这个按钮可能不存在或隐藏）
                        is_visible = await menu_button.is_visible()
                        if is_visible:
                            print(
                                f"  找到主菜单按钮（选择器: {selector}），点击展开..."
                            )
                            await menu_button.click()
                            await asyncio.sleep(1.5)
                            menu_expanded = True
                            break
                except Exception:
                    continue

            if not menu_expanded:
                print("  菜单可能已展开（未找到可见的菜单按钮）")

            # 步骤2: 点击临时对话按钮
            print("  查找临时对话按钮...")

            # 等待侧边栏完全展开
            await asyncio.sleep(1)

            # 临时对话按钮的多种选择器
            temp_chat_selectors = [
                # 基于 aria-label
                'button[aria-label*="临时"]',
                'button[aria-label*="Temporary"]',
                # 基于文本
                'button:has-text("临时对话")',
                'button:has-text("Temporary chat")',
                # 基于部分文本匹配
                '*:has-text("临时对话")',
                '*:has-text("Temporary chat")',
            ]

            for selector in temp_chat_selectors:
                try:
                    temp_button = await self.page.wait_for_selector(
                        selector, timeout=3000, state="visible"
                    )
                    if temp_button:
                        print(f"  ✓ 找到临时对话按钮（选择器: {selector}）")
                        await temp_button.click()
                        await asyncio.sleep(2)

                        # 验证：检查临时对话说明卡片是否出现
                        print("  验证临时对话模式是否启用...")
                        temp_card = await self.page.query_selector(
                            ".temporary-chat-card"
                        )

                        if temp_card:
                            # 检查卡片标题
                            card_title = await temp_card.query_selector(".gds-title-l")
                            if card_title:
                                title_text = await card_title.text_content()
                                print(f"  找到临时对话卡片，标题: {title_text}")

                                if "临时" in title_text or "Temporary" in title_text:
                                    print("✓ 临时对话模式已成功启用")
                                    return True

                        # 如果没找到卡片，可能已经在临时对话模式
                        print("  ⚠ 未找到临时对话卡片，但按钮已点击")
                        print("✓ 临时对话模式可能已启用")
                        return True
                except Exception:
                    continue

            # 如果所有选择器都失败，尝试通过文本内容直接匹配
            print("  尝试通过文本内容匹配...")
            try:
                # 获取侧边栏中的所有按钮
                all_buttons = await self.page.query_selector_all("button")

                for button in all_buttons:
                    try:
                        text = await button.text_content()
                        aria_label = await button.get_attribute("aria-label")

                        # 检查文本或 aria-label 是否包含"临时"或"Temporary"
                        if (
                            text and ("临时" in text or "temporary" in text.lower())
                        ) or (
                            aria_label
                            and (
                                "临时" in aria_label
                                or "temporary" in aria_label.lower()
                            )
                        ):
                            # 确保按钮可见
                            if await button.is_visible():
                                print(
                                    f"  ✓ 通过文本匹配找到: text='{text}', aria-label='{aria_label}'"
                                )
                                await button.click()
                                await asyncio.sleep(2)

                                # 验证：检查临时对话说明卡片是否出现
                                print("  验证临时对话模式是否启用...")
                                temp_card = await self.page.query_selector(
                                    ".temporary-chat-card"
                                )

                                if temp_card:
                                    card_title = await temp_card.query_selector(
                                        ".gds-title-l"
                                    )
                                    if card_title:
                                        title_text = await card_title.text_content()
                                        print(f"  找到临时对话卡片，标题: {title_text}")

                                        if (
                                            "临时" in title_text
                                            or "Temporary" in title_text
                                        ):
                                            print("✓ 临时对话模式已成功启用")
                                            return True

                                print("  ⚠ 未找到临时对话卡片，但按钮已点击")
                                print("✓ 临时对话模式可能已启用")
                                return True
                    except:
                        continue

            except Exception as e:
                print(f"  文本匹配失败: {e}")

            print("❌ 未找到临时对话按钮")
            return False

        except Exception as e:
            print(f"❌ 启用临时对话失败: {e}")
            return False

    async def start_new_chat(self) -> bool:
        """
        开启新对话（Ctrl+Shift+O）

        确保在干净的对话页面开始，避免历史对话影响生成

        Returns:
            是否成功开启新对话
        """
        print("\n开启新对话...")

        try:
            # 方法1: 使用快捷键 Ctrl+Shift+O
            print("  使用快捷键 Ctrl+Shift+O...")
            await self.page.keyboard.press("Control+Shift+O")

            # 只等待关键元素（输入框）出现，不等待整个页面 networkidle
            print("  等待输入框就绪...")
            await self.page.wait_for_selector('div[contenteditable="true"]', timeout=5000)

            # 验证是否成功（检查 URL 是否为 /app）
            current_url = self.page.url
            if "/app" in current_url:
                print(f"✓ 新对话已开启，当前URL: {current_url}")
                return True

            # 方法2: 如果快捷键失败，尝试导航到 /app
            print("  快捷键未生效，尝试导航到 /app...")
            # 不等待 networkidle，只等待 domcontentloaded
            await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")

            # 等待输入框出现
            await self.page.wait_for_selector('div[contenteditable="true"]', timeout=5000)

            current_url = self.page.url
            print(f"✓ 已导航到新对话页面: {current_url}")
            return True

        except Exception as e:
            print(f"❌ 开启新对话失败: {e}")
            return False

    async def activate_image_generation_stable(self) -> bool:
        """
        稳定的图片生成功能激活方法

        方法：
        1. 点击 Tools（智能体）菜单
        2. 点击"生成图片"选项
        3. 验证：检查输入框下方是否出现"取消选择图片"按钮

        Returns:
            是否成功激活
        """
        print("\n激活图片生成功能（稳定方法）...")

        try:
            # 先检查是否已经激活（避免重复激活）
            print("  检查是否已激活...")
            deselect_button = await self.page.query_selector(
                ".toolbox-drawer-item-deselect-button"
            )
            if deselect_button:
                label = await deselect_button.get_attribute("aria-label")
                if label and "图片" in label or "image" in label.lower():
                    print("✓ 图片生成功能已经激活")
                    return True

            # 步骤1: 点击 Tools（智能体/工具）菜单图标
            print("  查找 Tools 菜单图标...")

            tools_selectors = [
                # 最精确：基于 class（从真实DOM）
                "button.toolbox-drawer-button",
                # 备选：基于 aria-label
                'button[aria-label="工具"]',
                'button[aria-label="Tools"]',
                'button[aria-label*="工具"]',
                'button[aria-label*="智能体"]',
                'button[aria-label*="Tools"]',
                # 备选：基于 fonticon
                'button mat-icon[fonticon="page_info"]',
            ]

            tools_button = None
            for selector in tools_selectors:
                try:
                    tools_button = await self.page.wait_for_selector(
                        selector, timeout=3000, state="visible"
                    )
                    if tools_button:
                        print(f"  ✓ 找到 Tools 菜单（选择器: {selector}）")
                        break
                except Exception:
                    continue

            if not tools_button:
                print("  ❌ 未找到 Tools 菜单")
                return False

            # 点击 Tools 菜单
            await tools_button.click()
            print("  ✓ 已点击 Tools 菜单")
            await asyncio.sleep(1.5)  # 等待菜单展开

            # 步骤2: 查找并点击"生成图片"选项
            print("  查找'生成图片'选项...")

            # 调试：列出所有可见的菜单项
            try:
                # 尝试多种容器选择器
                menu_containers = [
                    '[role="menu"]',
                    ".menu-items",
                    ".tools-menu-items",
                    "mat-menu-panel",
                ]

                all_items = []
                for container_sel in menu_containers:
                    try:
                        container = await self.page.query_selector(container_sel)
                        if container:
                            items = await container.query_selector_all("*")
                            all_items.extend(items)
                            print(
                                f"  调试：在 {container_sel} 找到 {len(items)} 个元素"
                            )
                            break
                    except:
                        continue

                # 如果没找到容器，就搜索所有元素
                if not all_items:
                    all_items = await self.page.query_selector_all(
                        '[role="menuitem"], button, div'
                    )

                # 打印前几个包含"图片"或"image"的元素
                print("  调试：查找包含'图片'或'image'的元素...")
                count = 0
                for item in all_items[:50]:  # 只检查前50个
                    try:
                        text = await item.text_content()
                        if text and (
                            "图片" in text
                            or "image" in text.lower()
                            or "Create" in text
                        ):
                            print(f"    找到: {text.strip()[:50]}")
                            count += 1
                            if count >= 5:
                                break
                    except:
                        continue

            except Exception as e:
                print(f"  调试信息获取失败: {e}")

            # 尝试多种选择器点击"生成图片"
            image_gen_selectors = [
                # Playwright 文本选择器（最稳定）
                "text=生成图片",
                "text=Create images",
                'text="生成图片"',  # 精确匹配
                'text="Create images"',
                # 包含文本
                '*:has-text("生成图片")',
                '*:has-text("Create images")',
                # role + 文本
                '[role="menuitem"]:has-text("生成图片")',
                '[role="menuitem"]:has-text("Create images")',
                # button + 文本
                'button:has-text("生成图片")',
                'button:has-text("Create images")',
            ]

            clicked = False
            for selector in image_gen_selectors:
                try:
                    element = await self.page.wait_for_selector(
                        selector, timeout=2000, state="visible"
                    )
                    if element:
                        print(f"  ✓ 找到'生成图片'（选择器: {selector}）")
                        await element.click()
                        clicked = True
                        break
                except:
                    continue

            # 如果所有选择器都失败，尝试文本匹配
            if not clicked:
                print("  尝试通过文本内容直接匹配...")
                try:
                    # 获取所有可能的元素
                    all_elements = await self.page.query_selector_all(
                        'button, [role="menuitem"], div, span'
                    )

                    for element in all_elements:
                        try:
                            text = await element.text_content()
                            if not text:
                                continue

                            text = text.strip()
                            # 匹配"生成图片"或"Create images"
                            if (
                                text == "生成图片"
                                or text == "Create images"
                                or "生成图片" in text
                                or "Create images" in text
                            ):
                                print(f"  ✓ 通过文本匹配找到: '{text}'")
                                await element.click()
                                clicked = True
                                break
                        except:
                            continue

                except Exception as e:
                    print(f"  文本匹配失败: {e}")

            if not clicked:
                print("  ❌ 未能点击'生成图片'选项")
                return False

            # 步骤3: 验证激活成功
            print("  验证激活状态...")
            await asyncio.sleep(2)

            # 检查"取消选择图片"按钮是否出现
            deselect_button = await self.page.query_selector(
                ".toolbox-drawer-item-deselect-button"
            )

            if deselect_button:
                label = await deselect_button.get_attribute("aria-label")
                text = await deselect_button.text_content()
                print(f"  找到取消选择按钮: aria-label='{label}', text='{text}'")

                if (label and ("图片" in label or "image" in label.lower())) or (
                    text and ("图片" in text or "image" in text.lower())
                ):
                    print("✓ 图片生成功能已成功激活")
                    return True

            print("  ⚠ 未找到'取消选择图片'按钮，激活可能失败")
            return False

        except Exception as e:
            print(f"❌ 激活图片生成功能失败: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def edit_image_enhanced(
        self,
        input_image: str,
        prompt: str,
        output_dir: str = "output",
        model: Literal["Pro", "Fast"] = "Fast",
        temporary_chat: bool = False,
        output_format: str = "webp",
        webp_lossless: bool = True,
        save_log: bool = True,
    ) -> Optional[list[str]]:
        """
        增强版图片编辑方法

        Args:
            input_image: 输入图片路径
            prompt: 编辑指令
            output_dir: 输出目录
            model: 使用的模型（"Pro" 或 "Fast"）
            temporary_chat: 是否使用临时对话
            output_format: 输出格式
            webp_lossless: WebP无损压缩
            save_log: 是否保存事件日志

        Returns:
            生成图片的路径列表
        """
        import time

        # 计时辅助函数
        timings = {}
        def log_time(stage: str, start: float):
            elapsed = time.time() - start
            timings[stage] = elapsed
            print(f"  ⏱ [{stage}] {elapsed:.3f}s")

        total_start = time.time()

        print("=" * 60)
        print("开始增强版图片编辑流程")
        print("=" * 60)
        print(f"输入图片: {input_image}")
        print(f"编辑指令: {prompt}")
        print(f"输出目录: {output_dir}")
        print(f"使用模型: {model}")
        print(f"临时对话: {temporary_chat}")

        try:
            # 步骤1: 开启新对话（每次都执行，确保干净状态）
            stage_start = time.time()
            if not await self.start_new_chat():
                print("⚠ 开启新对话失败，继续执行")
            log_time("开启新对话", stage_start)

            # 步骤2: 可选 - 启用临时对话
            if temporary_chat:
                stage_start = time.time()
                if not await self.enable_temporary_chat():
                    print("⚠ 临时对话启用失败，继续使用普通对话")
                log_time("启用临时对话", stage_start)

            # 步骤3-7: 并行执行所有准备操作
            # 优先开始图片上传（最耗时），同时并行其他操作
            stage_start = time.time()
            print("\n并行执行: 模型选择 + 上传图片 + 输入Prompt + 激活图片生成...")

            async def model_selection_task():
                """确保模型选择正确"""
                return await self.ensure_model_selection(model)

            async def upload_image_task():
                """上传图片（最耗时，优先开始）"""
                upload_success = await self.upload_image_by_paste(input_image)
                if not upload_success:
                    print("⚠ 粘贴上传失败，尝试点击上传方式...")
                    upload_success = await self.upload_image(input_image)
                return upload_success

            async def input_prompt_task():
                """输入prompt"""
                return await self.input_prompt(prompt)

            async def activate_image_gen():
                """激活图片生成功能"""
                return await self.activate_image_generation_stable()

            # 并行执行四个任务
            results = await asyncio.gather(
                model_selection_task(),
                upload_image_task(),
                input_prompt_task(),
                activate_image_gen(),
                return_exceptions=True
            )

            # 检查结果
            if not results[0]:
                print("⚠ 模型选择可能未成功，继续执行")
            if not results[1]:
                print("❌ 图片上传失败")
                return None
            if not results[2]:
                print("❌ Prompt输入失败")
                return None
            if not results[3]:
                print("❌ 激活图片生成功能失败")
                return None

            log_time("并行准备(模型+上传+输入+激活)", stage_start)

            # 步骤8: 提交（提交后才开始计时等待生成）
            stage_start = time.time()
            if not await self.submit_generation():
                print("❌ 提交失败")
                return None
            log_time("提交请求", stage_start)

            # 步骤8: 等待生成（从提交后开始计时，最多2分钟）
            stage_start = time.time()
            generation_timeout = 120  # 2分钟
            generation_success = await self.wait_for_generation(timeout=generation_timeout)
            if not generation_success:
                print(f"⚠ 生成超时（{generation_timeout}秒），额外等待10秒让图片渲染...")
                await asyncio.sleep(10)  # 即使超时，也给图片一些渲染时间
            log_time("等待生成", stage_start)

            # 步骤9: 获取图片
            stage_start = time.time()
            image_urls = await self.get_generated_images()
            log_time("获取图片URL", stage_start)

            if not image_urls:
                print("❌ 未找到生成的图片")
                print("  提示: 请检查页面是否有错误提示或需要人工验证")
                return None

            # 下载图片
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            output_paths = []

            # 创建日期目录
            from datetime import datetime
            date_dir = datetime.now().strftime("%Y%m%d")
            output_date_path = output_path / date_dir
            output_date_path.mkdir(parents=True, exist_ok=True)

            print(f"\n正在下载图片（{output_format.upper()}格式）...")
            stage_start = time.time()
            for i, url in enumerate(image_urls):
                download_start = time.time()
                print(f"  URL: {url[:80]}...")

                if output_format == "webp":
                    # 直接下载并获取SHA摘要
                    temp_path = output_date_path / f"temp_{i}.webp"

                    success, file_hash = await self.download_image_as_webp(
                        url, str(temp_path), lossless=webp_lossless
                    )

                    if success and file_hash:
                        # 重命名为SHA摘要文件名
                        final_path = output_date_path / f"{file_hash}.webp"
                        temp_path.rename(final_path)
                        output_paths.append(str(final_path))
                        print(f"  ✓ 文件名: {file_hash}.webp")
                else:  # png 或 jpg
                    # 直接下载并获取SHA摘要
                    temp_path = output_date_path / f"temp_{i}.{output_format}"

                    success, file_hash = await self.download_image(url, str(temp_path))

                    if success and file_hash:
                        # 重命名为SHA摘要文件名
                        final_path = output_date_path / f"{file_hash}.{output_format}"
                        temp_path.rename(final_path)
                        output_paths.append(str(final_path))
                        print(f"  ✓ 文件名: {file_hash}.{output_format}")

                print(f"  ⏱ [下载图片{i+1}] {time.time() - download_start:.3f}s")
            log_time("下载全部图片", stage_start)

            total_elapsed = time.time() - total_start

            print("\n" + "=" * 60)
            print(f"✓ 图片编辑完成！共生成 {len(output_paths)} 张图片")
            print("=" * 60)
            for path in output_paths:
                print(f"  {path}")

            # 打印计时汇总
            print("\n" + "-" * 60)
            print("⏱ 各阶段耗时汇总:")
            print("-" * 60)
            for stage, elapsed in timings.items():
                pct = (elapsed / total_elapsed) * 100
                bar_len = int(pct / 2)
                bar = "█" * bar_len + "░" * (50 - bar_len)
                print(f"  {stage:16s} {elapsed:6.3f}s ({pct:5.1f}%) {bar}")
            print("-" * 60)
            print(f"  {'总耗时':16s} {total_elapsed:6.3f}s")
            print("-" * 60)

            # 保存事件日志
            if save_log and self.event_log:
                log_path = output_path / "event_log.json"
                self.save_event_log(str(log_path))

            # 任务完成后进入新对话，为下次任务做准备
            try:
                print("\n进入新对话（为下次任务预热）...")
                new_chat_start = time.time()
                if await self.start_new_chat():
                    log_time("进入新对话", new_chat_start)
                else:
                    print("⚠ 进入新对话失败")
            except Exception as e:
                print(f"⚠ 进入新对话出错: {e}")

            return output_paths if output_paths else None

        except Exception as e:
            print(f"\n❌ 图片编辑流程出错: {e}")
            import traceback

            traceback.print_exc()
            return None


# 使用示例
async def main():
    """示例：使用增强版编辑器"""

    # 创建编辑器（启用事件日志）
    editor = EnhancedGeminiImageEditor(
        account_id=0, headless=False, enable_logging=True
    )

    try:
        # 启动浏览器
        await editor.launch()

        # 编辑图片
        result_paths = await editor.edit_image_enhanced(
            input_image="test/lamp.webp",
            prompt="把这个灯变成蓝色的",
            output_dir="output/lamp_blue_enhanced",
            wait_time=30,
            model="Fast",  # 使用 Fast 模型
            temporary_chat=False,  # 不使用临时对话
            output_format="webp",
            webp_lossless=True,
            save_log=True,  # 保存事件日志
        )

        if result_paths:
            print(f"\n成功生成 {len(result_paths)} 张图片")

    finally:
        await editor.close()


if __name__ == "__main__":
    asyncio.run(main())
