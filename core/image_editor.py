"""
Gemini 图片编辑器

提供完整的图片编辑功能API
"""

import asyncio
from pathlib import Path
from typing import List, Optional

from .browser import (
    AGREE_BUTTON,
    DOWNLOAD_BUTTON,
    IMAGE_GEN_DESELECT,
    INPUT_BOX,
    RESPONSE_CONTAINER,
    SUBMIT_BUTTON,
    UPLOAD_MENU_BUTTON,
    is_generated_image,
)
from .gemini_browser import GeminiBrowser
from .watermark_remover import WatermarkRemover


class GeminiImageEditor(GeminiBrowser):
    """Gemini图片编辑器 - 扩展自GeminiBrowser"""

    def __init__(
        self,
        account_id: int = 0,
        headless: bool = True,
        proxy: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
    ):
        super().__init__(account_id, headless, proxy, user_data_dir)
        self.default_timeout = 60000  # 60秒

    async def navigate_to_new_chat(self):
        """导航到新对话页面"""
        if not self.page:
            raise RuntimeError("浏览器未启动，请先调用 launch()")

        current_url = self.page.url
        if "/app" not in current_url:
            await self.page.goto("https://gemini.google.com/app")
            # 等待页面加载完成（事件驱动）
            await self.page.wait_for_load_state("networkidle", timeout=10000)

        print("✓ 已在对话页面")

    async def click_image_generation_button(self):
        """点击图片生成按钮（适配中英文，JS点击+fallback机制）"""
        print("\n正在激活图片生成功能...")

        # 中英文选择器
        button_selectors = [
            'button[aria-label*="制作图片"]',  # 中文
            'button[aria-label*="Create image"]',  # 英文
            'button[aria-label*="Generate image"]',  # 英文备选
        ]

        try:
            # 尝试所有选择器
            for selector in button_selectors:
                try:
                    button = await self.page.wait_for_selector(selector, timeout=3000)
                    if button:
                        # 先尝试 JS 点击（快速）
                        try:
                            await self.page.evaluate("(btn) => btn.click()", button)
                            # 等待激活：工具栏出现或输入框工具栏就绪
                            await self.page.wait_for_selector(
                                ".toolbox-drawer-item-deselect-button, .input-area-actions",
                                state="visible",
                                timeout=2000,
                            )
                            print("✓ 图片生成功能已激活 [js]")
                            return True
                        except Exception:
                            # JS 点击失败或等待超时，fallback 到 no_wait_after
                            print("  ⚠ JS 点击失败，fallback 到 no_wait_after")
                            try:
                                await button.click(no_wait_after=True)
                                # fallback 也用 wait 验证激活
                                await self.page.wait_for_selector(
                                    ".toolbox-drawer-item-deselect-button, .input-area-actions",
                                    state="visible",
                                    timeout=2000,
                                )
                                print("✓ 图片生成功能已激活 [no_wait]")
                                return True
                            except Exception:
                                # 两次都失败
                                print("❌ 激活失败（工具栏未出现）")
                                return False
                except Exception:
                    continue

            print("❌ 未找到图片生成按钮")
            return False
        except Exception as e:
            print(f"❌ 激活图片生成功能失败: {e}")
            return False

    async def upload_image_by_paste(self, image_path: str) -> bool:
        """
        通过模拟粘贴上传图片（最快最可靠的方法）

        Args:
            image_path: 图片文件路径

        Returns:
            是否粘贴成功（不等待加载验证）
        """
        print(f"\n正在上传图片（粘贴方式）: {image_path}")

        image_file = Path(image_path)
        if not image_file.exists():
            print(f"❌ 图片文件不存在: {image_path}")
            return False

        try:
            # 等待输入框就绪
            print("  等待输入框就绪...")
            input_box = await self.page.wait_for_selector(
                INPUT_BOX, state="visible", timeout=10000
            )

            if not input_box:
                print("❌ 未找到输入框")
                return False

            print("  ✓ 找到输入框，点击聚焦")
            await input_box.click()
            # 聚焦后不需要等待，粘贴操作本身会触发

            # 读取图片文件并转换为 base64
            import base64

            with open(image_file, "rb") as f:
                image_data = f.read()

            image_base64 = base64.b64encode(image_data).decode()

            # 检测文件类型和扩展名
            mime_type = "image/webp"
            file_ext = ".webp"
            suffix = image_file.suffix.lower()
            if suffix in [".jpg", ".jpeg"]:
                mime_type = "image/jpeg"
                file_ext = ".jpg"
            elif suffix == ".png":
                mime_type = "image/png"
                file_ext = ".png"

            print(f"  图片类型: {mime_type}, 大小: {len(image_data)} bytes")

            # 使用 JavaScript 模拟粘贴操作
            print("  执行粘贴操作...")
            paste_result = await self.page.evaluate(
                """
                async (args) => {
                    const [imageBase64, mimeType, fileExt] = args;
                    try {
                        // 将 base64 转换为 Blob
                        const byteCharacters = atob(imageBase64);
                        const byteNumbers = new Array(byteCharacters.length);
                        for (let i = 0; i < byteCharacters.length; i++) {
                            byteNumbers[i] = byteCharacters.charCodeAt(i);
                        }
                        const byteArray = new Uint8Array(byteNumbers);
                        const blob = new Blob([byteArray], { type: mimeType });

                        // 创建 File 对象（必须带扩展名）
                        const file = new File([blob], "pasted_image" + fileExt, { type: mimeType });

                        // 创建 DataTransfer 对象
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(file);

                        // 获取输入框
                        const target = document.querySelector('div[contenteditable="true"]');
                        if (!target) {
                            return { success: false, error: "Target not found" };
                        }

                        // 创建并触发 paste 事件
                        const pasteEvent = new ClipboardEvent('paste', {
                            bubbles: true,
                            cancelable: true,
                            clipboardData: dataTransfer
                        });

                        target.focus();
                        const dispatched = target.dispatchEvent(pasteEvent);

                        return { success: true, dispatched: dispatched };
                    } catch (error) {
                        return { success: false, error: error.message };
                    }
                }
            """,
                [image_base64, mime_type, file_ext],
            )

            if not paste_result.get("success"):
                print(f"❌ 粘贴失败: {paste_result.get('error')}")
                return False

            print("  ✓ 粘贴事件已触发")
            return True

        except Exception as e:
            print(f"❌ 粘贴上传失败: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def _dismiss_consent_dialog(self) -> bool:
        """
        检测并关闭同意/确认弹窗（如图片权利确认、隐私政策等）

        在粘贴图片后，可能会弹出 "Create content from images" 对话框，
        需要点击 "Agree" / "同意" 按钮才能继续。

        此方法不等待，只检查当前是否有弹窗并尝试关闭。

        Returns:
            是否成功关闭弹窗（没有弹窗也返回 False）
        """
        try:
            for selector in AGREE_BUTTON:
                try:
                    button = await self.page.query_selector(selector)
                    if button and await button.is_visible():
                        print("  ⚠ 检测到弹窗，点击同意按钮...")
                        await button.click()  # 等待弹窗关闭（应该不用sleep,会自动等待副作用结束）
                        print("  ✓ 弹窗已关闭")
                        return True
                except Exception:
                    continue

            return False

        except Exception as e:
            print(f"  ⚠ 弹窗检测异常: {e}")
            return False

    async def verify_image_loaded(self, timeout: int = 20) -> bool:
        """
        验证图片是否加载成功（等待页面上出现 blob URL 的图片）

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否检测到图片加载
        """
        print("  验证图片加载...")
        try:
            # 等待带有 blob: 前缀的图片元素出现（事件驱动）
            img = await self.page.wait_for_selector(
                'img[src^="blob:"]', timeout=timeout * 1000, state="visible"
            )

            if img:
                src = await img.get_attribute("src")
                print(f"✓ 检测到图片已加载: {src[:80]}...")
                return True

            return False

        except Exception:
            print("⚠ 图片加载验证超时（可能仍在后台加载）")
            return False

    async def upload_image(self, image_path: str) -> bool:
        """
        上传图片（点击按钮方式，作为粘贴方式的备用）

        Args:
            image_path: 图片文件路径

        Returns:
            是否上传成功
        """
        print(f"\n正在上传图片（点击方式）: {image_path}")

        image_file = Path(image_path)
        if not image_file.exists():
            print(f"❌ 图片文件不存在: {image_path}")
            return False

        try:
            # 设置file chooser拦截器
            file_chooser_triggered = False

            async def handle_file_chooser(file_chooser):
                nonlocal file_chooser_triggered
                file_chooser_triggered = True
                print("  ✓ 捕获到file chooser")
                await file_chooser.set_files(str(image_file.absolute()))
                print(f"  ✓ 文件已设置: {image_file.name}")

            self.page.on("filechooser", handle_file_chooser)

            # 步骤1: 等待并点击"打开文件上传菜单"按钮（中英文适配）
            upload_button_selectors = [
                'button[aria-label="打开文件上传菜单"]',  # 中文
                'button[aria-label="Open file upload menu"]',  # 英文
                'button[aria-label*="Add files"]',  # 英文 - 添加文件
                'button[aria-label*="上传"]',  # 中文备选
                'button[aria-label*="upload"]',  # 英文备选
            ]

            upload_button = None
            print("  等待上传按钮就绪...")

            for selector in upload_button_selectors:
                try:
                    upload_button = await self.page.wait_for_selector(
                        selector, state="visible", timeout=3000
                    )
                    if upload_button:
                        break
                except Exception:
                    continue

            if not upload_button:
                print("❌ 未找到上传按钮")
                return False

            print("  ✓ 找到上传按钮，立即点击")
            await upload_button.click()
            # 已经有 wait_for_selector 等待菜单容器，不需要 sleep

            # 步骤2: 等待并点击菜单中的"上传文件"选项（使用事件驱动）
            print("  等待上传文件选项出现...")

            # 使用 wait_for_selector 事件驱动等待上传按钮（更高效）
            upload_keywords = ["上传文件", "upload file", "upload files"]
            upload_option = None

            # 先等待菜单容器出现
            try:
                menu_container = await self.page.wait_for_selector(
                    '[role="menu"], [role="listbox"], [role="dialog"]',
                    state="visible",
                    timeout=3000,
                )
                if menu_container:
                    print("  ✓ 菜单容器已出现")
                    # 在菜单内查找上传按钮
                    buttons = await menu_container.query_selector_all("button")
                    for btn in buttons:
                        if not await btn.is_visible():
                            continue

                        aria_label = await btn.get_attribute("aria-label") or ""
                        text = await btn.text_content() or ""
                        combined = (aria_label + text).lower()

                        if any(
                            keyword.lower() in combined for keyword in upload_keywords
                        ):
                            upload_option = btn
                            print("  ✓ 找到上传文件选项")
                            break
            except Exception:
                pass

            if not upload_option:
                print("❌ 未找到上传文件选项")
                return False

            # 步骤3: 点击"上传文件"选项，触发file chooser
            print("  ✓ 立即点击上传选项")
            await upload_option.click()

            # 等待file chooser被触发和处理（减少等待时间）
            await asyncio.sleep(2)

            if not file_chooser_triggered:
                print("⚠ File chooser未被触发")
                return False

            # 验证上传成功（使用事件驱动等待 blob URL 图片）
            print("  等待图片加载...")
            try:
                # 使用 wait_for_selector 事件驱动等待 blob: 图片出现
                blob_img = await self.page.wait_for_selector(
                    'img[src^="blob:"]', state="visible", timeout=5000  # 最多等待5秒
                )
                if blob_img:
                    src = await blob_img.get_attribute("src")
                    print(f"✓ 图片上传成功: {src[:80]}...")
                    return True
            except Exception:
                print("⚠ 文件已设置但未检测到blob图片")
                return False

        except Exception as e:
            print(f"❌ 上传图片失败: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def input_prompt(self, prompt: str) -> bool:
        """
        输入编辑prompt（优化版：使用wait等待就绪）

        Args:
            prompt: 编辑指令文本

        Returns:
            是否输入成功
        """
        print(f"\n正在输入prompt: {prompt}")

        try:
            # 等待contenteditable的输入框就绪
            print("  等待输入框就绪...")
            prompt_input = await self.page.wait_for_selector(
                INPUT_BOX, state="visible", timeout=10000
            )

            if prompt_input:
                print("  ✓ 输入框就绪，立即输入")
                await prompt_input.fill(prompt)
                # fill 操作本身会等待输入完成，不需要额外 sleep
                print("✓ Prompt输入成功")
                return True
            else:
                print("❌ 未找到prompt输入框")
                return False

        except Exception as e:
            print(f"❌ 输入prompt失败: {e}")
            return False

    async def submit_generation(self) -> bool:
        """
        提交生成请求（适配中英文）

        Returns:
            是否提交成功
        """
        print("\n正在提交生成请求...")

        try:
            submit_button = None
            for selector in SUBMIT_BUTTON:
                try:
                    submit_button = await self.page.wait_for_selector(
                        selector, state="visible", timeout=3000
                    )
                    if submit_button:
                        break
                except Exception:
                    continue

            if submit_button:
                await submit_button.click()
                print("✓ 生成请求已提交")
                return True
            else:
                print("❌ 未找到提交按钮")
                return False

        except Exception as e:
            print(f"❌ 提交失败: {e}")
            return False

    async def wait_for_generation(self, timeout: int = 60) -> bool:
        """
        等待图片生成完成（使用事件驱动等待 googleusercontent 图片出现）

        策略：使用 wait_for_function 事件驱动等待最后一个对话容器内出现
        googleusercontent 图片，不需要轮询

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否生成成功
        """
        print(f"\n等待图片生成完成（最多{timeout}秒）...")

        try:
            # 使用 wait_for_function 事件驱动等待图片出现
            await self.page.wait_for_function(
                """
                () => {
                    // 定位最后一个对话容器
                    const selectors = ['model-response', 'response-container'];
                    let container = null;

                    for (const selector of selectors) {
                        const containers = document.querySelectorAll(selector);
                        if (containers.length > 0) {
                            container = containers[containers.length - 1];
                            break;
                        }
                    }

                    if (!container) return false;

                    // 在容器内搜索 googleusercontent 图片（排除头像）
                    const images = container.querySelectorAll('img');
                    for (const img of images) {
                        const src = img.src || '';
                        if (src.includes('googleusercontent') && !src.includes('/a/ACg8oc')) {
                            return true;  // 找到生成的图片
                        }
                    }

                    return false;
                }
                """,
                timeout=timeout * 1000,
            )

            # 统计图片数量
            container_selectors = [
                "model-response",
                "message-content model-response",
                "response-container",
            ]

            for selector in container_selectors:
                try:
                    containers = await self.page.query_selector_all(selector)
                    if containers:
                        container = containers[-1]
                        images = await container.query_selector_all("img")
                        generated_count = 0

                        for img in images:
                            src = await img.get_attribute("src")
                            if (
                                src
                                and "googleusercontent" in src
                                and "/a/ACg8oc" not in src
                            ):
                                generated_count += 1

                        if generated_count > 0:
                            print(f"✓ 检测到 {generated_count} 张生成的图片")
                            return True
                        break
                except Exception:
                    continue

            print("✓ 图片生成完成")
            return True

        except Exception:
            print(f"⚠ 等待超时（{timeout}秒），停止等待")
            return False

    async def get_generated_images(self) -> List[str]:
        """
        获取生成的图片URL列表（去重，排除头像）
        通过定位最新的对话消息容器来精确获取图片

        注意：不等待URL更新，因为我们优先使用hover按钮下载（不依赖URL）

        Returns:
            图片URL列表（已去重，排除头像）
        """
        # 策略：定位最新的模型回复容器
        print("\n正在定位最新的对话回复...")

        container = None
        for selector in RESPONSE_CONTAINER:
            try:
                containers = await self.page.query_selector_all(selector)
                if containers:
                    container = containers[-1]  # 取最后一个（最新的回复）
                    print(f"✓ 找到对话容器（使用选择器: {selector}）")
                    break
            except Exception as e:
                print(f"  尝试选择器 {selector} 失败: {e}")
                continue

        # 如果找到容器，只在容器内搜索图片
        if container:
            print("  在最新对话容器内搜索图片...")
            images = await container.query_selector_all("img")
        else:
            print("  ⚠ 未找到对话容器，回退到全局搜索")
            images = await self.page.query_selector_all("img")

        # 存储图片信息：(src, index, base_url)
        image_info = []
        thumbnail_info = []  # 分别存储缩略图

        print("正在分析页面上的图片...")

        for idx, img in enumerate(images):
            src = await img.get_attribute("src")
            alt = await img.get_attribute("alt")

            # 使用统一的过滤函数
            if not is_generated_image(src):
                continue

            # 额外检查 alt 属性排除头像
            if alt and any(
                keyword in alt for keyword in ["个人资料", "照片", "profile", "photo"]
            ):
                continue

            import re
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(src)

            # Google图片URL的尺寸参数在路径末尾
            path = parsed.path
            # 移除 =w..., =s..., =h... 等尺寸参数
            path_without_size = re.sub(r"=[wsh]\d+.*$", "", path)

            base_url = urlunparse(
                (parsed.scheme, parsed.netloc, path_without_size, "", "", "")
            )

            # 区分缩略图和高清图
            is_thumbnail = "w160" in src or "h160" in src

            if is_thumbnail:
                print(f"  跳过缩略图[{idx}]: {src[:100]}...")
                thumbnail_info.append((src, idx, base_url))
            else:
                print(f"  [{idx}] Full URL: {src}")
                print(f"       Base URL: {base_url}")
                image_info.append((src, idx, base_url))

        # 去重策略：按base URL去重
        url_map = {}  # base_url -> src

        # 优先使用高清图
        for src, idx, base_url in image_info:
            if base_url not in url_map:
                url_map[base_url] = src
            else:
                print(f"  警告：发现重复的base URL: {base_url[:80]}...")

        # 如果没有高清图，使用缩略图（WebP转换会重新渲染）
        if not url_map and thumbnail_info:
            print("\n  注意：只找到缩略图，将使用缩略图URL（下载时会重新获取完整图片）")
            for src, idx, base_url in thumbnail_info:
                if base_url not in url_map:
                    url_map[base_url] = src

        generated_urls = list(url_map.values())

        print(f"\n✓ 找到 {len(generated_urls)} 张生成的图片（已去重）")
        return generated_urls

    async def download_generated_image_by_index(
        self,
        index: int,
        save_path: str,
        lossless: bool = True,
        click_method: str = "no_wait",
        output_format: str = "webp",
        remove_watermark: bool = True,
    ) -> tuple[bool, str | None]:
        """
        按索引下载生成的图片（优先 hover 下载，失败时获取 URL 并用 request API）

        Args:
            index: 图片索引（0-based）
            save_path: 保存路径
            lossless: WebP 是否使用无损压缩，默认 True（推荐）
            click_method: 点击方法 (js/force/no_wait/normal)，默认 no_wait
            output_format: 输出格式 - "webp" 或 "png"
            remove_watermark: 是否去除水印，默认 True

        Returns:
            (是否下载成功, SHA256摘要)
        """
        import time

        # 获取最后一个对话容器中的图片
        container_selectors = [
            "model-response",
            "message-content model-response",
            "response-container",
        ]

        target_img = None
        for selector in container_selectors:
            try:
                containers = await self.page.query_selector_all(selector)
                if containers:
                    container = containers[-1]
                    images = await container.query_selector_all("img")

                    # 过滤出生成的图片（排除头像）
                    generated_images = []
                    for img in images:
                        src = await img.get_attribute("src")
                        if (
                            src
                            and "googleusercontent" in src
                            and "/a/ACg8oc" not in src
                        ):
                            generated_images.append(img)

                    if index < len(generated_images):
                        target_img = generated_images[index]
                        break
            except Exception:
                continue

        if not target_img:
            print(f"  ❌ 未找到索引为 {index} 的图片")
            return False, None

        # 获取图片 URL（用于 fallback）
        url = await target_img.get_attribute("src")

        # 方法1: 尝试通过 hover 下载按钮获取高质量原图
        print(f"\n正在下载图片 {index + 1}...")
        download_start = time.time()
        image_bytes = await self._download_via_hover_button_by_element(
            target_img, click_method
        )

        if image_bytes:
            download_time = time.time() - download_start
            print(
                f"    ⏱ [hover下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)"
            )
        else:
            # 方法2: 回退到 request API（此时 URL 已经稳定）
            print("  回退到 request API 下载...")
            download_start = time.time()
            response = await self.page.request.get(url)
            if response.ok:
                image_bytes = await response.body()
                download_time = time.time() - download_start
                print(
                    f"    ⏱ [request下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)"
                )
            else:
                print(f"  ❌ 下载失败，HTTP状态: {response.status}")
                return False, None

        # 保存图片
        if output_format == "webp":
            return await self._save_as_webp(
                image_bytes, save_path, lossless, remove_watermark
            )
        else:
            return await self._save_as_png(image_bytes, save_path, remove_watermark)

    async def download_image_as_webp(
        self,
        url: str,
        save_path: str,
        lossless: bool = True,
        click_method: str = "no_wait",
        remove_watermark: bool = True,
    ) -> tuple[bool, str | None]:
        """
        下载图片并转换为 WebP 格式（更小的文件体积）

        优先使用 hover 下载按钮获取高质量原图，失败则回退到 page.request.get

        Args:
            url: 图片URL
            save_path: 保存路径（会自动改为.webp扩展名）
            lossless: 是否使用无损压缩，默认 True（推荐）
            click_method: 点击方法 (js/force/no_wait/normal)，默认 no_wait
            remove_watermark: 是否去除水印，默认 True

        Returns:
            (是否下载成功, SHA256摘要)
        """
        import hashlib
        import time

        # 确保保存路径使用 .webp 扩展名
        save_path_obj = Path(save_path)
        save_path_webp = str(save_path_obj.with_suffix(".webp"))

        try:
            from io import BytesIO

            from PIL import Image

            image_bytes = None

            # 方法1: 尝试通过 hover 下载按钮获取高质量原图
            download_start = time.time()
            image_bytes = await self._download_via_hover_button(url, click_method)
            if image_bytes:
                download_time = time.time() - download_start
                print(
                    f"    ⏱ [hover下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)"
                )

            # 方法2: 回退到 page.request.get
            if not image_bytes:
                print("  回退到 request API 下载...")
                download_start = time.time()
                response = await self.page.request.get(url)
                if response.ok:
                    image_bytes = await response.body()
                    download_time = time.time() - download_start
                    print(
                        f"    ⏱ [request下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)"
                    )
                else:
                    print(f"  ❌ 下载失败，HTTP状态: {response.status}")
                    return False, None

            # 解码图片
            decode_start = time.time()
            img = Image.open(BytesIO(image_bytes))
            width, height = img.size
            original_size = len(image_bytes)
            decode_time = time.time() - decode_start
            print(f"    ⏱ [图片解码] {decode_time:.3f}s (尺寸: {width}x{height})")

            # 去除水印（如果启用）
            if remove_watermark:
                watermark_start = time.time()
                img = WatermarkRemover.remove_watermark(
                    img, watermark_size=None, verbose=True
                )
                watermark_time = time.time() - watermark_start
                print(f"    ⏱ [水印去除] {watermark_time:.3f}s")

            # 转换为 WebP（保存到内存）
            convert_start = time.time()
            webp_buffer = BytesIO()
            if lossless:
                img.save(webp_buffer, "WEBP", lossless=True)
            else:
                img.save(webp_buffer, "WEBP", quality=80)
            webp_data = webp_buffer.getvalue()
            convert_time = time.time() - convert_start

            # 计算 WebP 数据的 SHA256 摘要（完整 base64url 格式，去除填充符号）
            hash_start = time.time()
            import base64

            sha256_hash = hashlib.sha256(webp_data).digest()
            # 使用 base64url 编码（URL安全），并去除填充符号 '='
            file_hash = (
                base64.urlsafe_b64encode(sha256_hash).decode("ascii").rstrip("=")
            )
            hash_time = time.time() - hash_start

            # 保存文件
            save_file = Path(save_path_webp)
            save_file.parent.mkdir(parents=True, exist_ok=True)

            save_start = time.time()
            with open(save_file, "wb") as f:
                f.write(webp_data)
            save_time = time.time() - save_start

            # 统计信息
            webp_size = len(webp_data)
            compression = (1 - webp_size / original_size) * 100 if original_size else 0
            mode_text = "无损" if lossless else "有损"

            print(f"    ⏱ [WebP转换] {convert_time:.3f}s ({mode_text})")
            print(f"    ⏱ [SHA256计算] {hash_time:.3f}s")
            print(f"    ⏱ [文件保存] {save_time:.3f}s")
            print(f"  ✓ 已保存: {save_path_webp}")
            print(
                f"    原始: {original_size/1024:.1f}KB → WebP: {webp_size/1024:.1f}KB (压缩率: {compression:.1f}%)"
            )

            return True, file_hash

        except ImportError:
            print("  ❌ 需要安装 Pillow 库: pip install Pillow")
            return False, None
        except Exception as e:
            print(f"❌ WebP下载失败: {e}")
            import traceback

            traceback.print_exc()
            return False, None

    async def _save_as_webp(
        self,
        image_bytes: bytes,
        save_path: str,
        lossless: bool = True,
        remove_watermark: bool = True,
    ) -> tuple[bool, str | None]:
        """将图片字节数据保存为 WebP 格式（可选去除水印）"""
        import base64
        import hashlib
        import time
        from io import BytesIO

        from PIL import Image

        try:
            save_path_obj = Path(save_path)
            save_path_webp = str(save_path_obj.with_suffix(".webp"))

            # 解码图片
            decode_start = time.time()
            img = Image.open(BytesIO(image_bytes))
            width, height = img.size
            original_size = len(image_bytes)
            decode_time = time.time() - decode_start
            print(f"    ⏱ [图片解码] {decode_time:.3f}s (尺寸: {width}x{height})")

            # 去除水印（如果启用）
            if remove_watermark:
                watermark_start = time.time()
                img = WatermarkRemover.remove_watermark(
                    img, watermark_size=None, verbose=True
                )
                watermark_time = time.time() - watermark_start
                print(f"    ⏱ [水印去除] {watermark_time:.3f}s")

            # 转换为 WebP
            convert_start = time.time()
            webp_buffer = BytesIO()
            if lossless:
                img.save(webp_buffer, "WEBP", lossless=True)
            else:
                img.save(webp_buffer, "WEBP", quality=80)
            webp_data = webp_buffer.getvalue()
            convert_time = time.time() - convert_start

            # 计算 SHA256 摘要
            hash_start = time.time()
            sha256_hash = hashlib.sha256(webp_data).digest()
            file_hash = (
                base64.urlsafe_b64encode(sha256_hash).decode("ascii").rstrip("=")
            )
            hash_time = time.time() - hash_start

            # 保存文件
            save_file = Path(save_path_webp)
            save_file.parent.mkdir(parents=True, exist_ok=True)

            save_start = time.time()
            with open(save_file, "wb") as f:
                f.write(webp_data)
            save_time = time.time() - save_start

            # 统计信息
            webp_size = len(webp_data)
            compression = (1 - webp_size / original_size) * 100 if original_size else 0
            mode_text = "无损" if lossless else "有损"

            print(f"    ⏱ [WebP转换] {convert_time:.3f}s ({mode_text})")
            print(f"    ⏱ [SHA256计算] {hash_time:.3f}s")
            print(f"    ⏱ [文件保存] {save_time:.3f}s")
            print(f"  ✓ 已保存: {save_path_webp}")
            print(
                f"    原始: {original_size/1024:.1f}KB → WebP: {webp_size/1024:.1f}KB (压缩率: {compression:.1f}%)"
            )

            return True, file_hash

        except Exception as e:
            print(f"  ❌ WebP保存失败: {e}")
            import traceback

            traceback.print_exc()
            return False, None

    async def _save_as_png(
        self, image_bytes: bytes, save_path: str, remove_watermark: bool = True
    ) -> tuple[bool, str | None]:
        """将图片字节数据保存为 PNG 格式（可选去除水印）"""
        import base64
        import hashlib
        import time
        from io import BytesIO

        from PIL import Image

        try:
            # 如果启用了水印去除,先处理图片
            if remove_watermark:
                # 解码图片
                decode_start = time.time()
                img = Image.open(BytesIO(image_bytes))
                width, height = img.size
                decode_time = time.time() - decode_start
                print(f"    ⏱ [图片解码] {decode_time:.3f}s (尺寸: {width}x{height})")

                # 去除水印
                watermark_start = time.time()
                img = WatermarkRemover.remove_watermark(
                    img, watermark_size=None, verbose=True
                )
                watermark_time = time.time() - watermark_start
                print(f"    ⏱ [水印去除] {watermark_time:.3f}s")

                # 重新编码为字节数据
                output = BytesIO()
                img.save(output, format="PNG")
                image_bytes = output.getvalue()

            # 计算 SHA256 摘要
            hash_start = time.time()
            sha256_hash = hashlib.sha256(image_bytes).digest()
            file_hash = (
                base64.urlsafe_b64encode(sha256_hash).decode("ascii").rstrip("=")
            )
            hash_time = time.time() - hash_start

            # 保存文件
            save_file = Path(save_path)
            save_file.parent.mkdir(parents=True, exist_ok=True)

            save_start = time.time()
            with open(save_file, "wb") as f:
                f.write(image_bytes)
            save_time = time.time() - save_start

            print(f"    ⏱ [SHA256计算] {hash_time:.3f}s")
            print(f"    ⏱ [文件保存] {save_time:.3f}s")
            print(f"  ✓ 已保存: {save_path} ({len(image_bytes)/1024:.1f}KB)")

            return True, file_hash

        except Exception as e:
            print(f"  ❌ PNG保存失败: {e}")
            import traceback

            traceback.print_exc()
            return False, None

    async def _download_via_hover_button_by_element(
        self, img_element, click_method: str = "no_wait"
    ) -> bytes | None:
        """
        通过图片元素 hover 触发下载按钮

        Args:
            img_element: 图片元素
            click_method: 点击方法

        Returns:
            图片字节数据，失败返回 None
        """
        try:
            # Hover 到图片上，触发下载按钮显示
            await self.page.evaluate(
                """
                (img) => {
                    const rect = img.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;

                    const mouseoverEvent = new MouseEvent('mouseover', {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    });

                    const mouseenterEvent = new MouseEvent('mouseenter', {
                        bubbles: false,
                        cancelable: false,
                        view: window,
                        clientX: x,
                        clientY: y
                    });

                    img.dispatchEvent(mouseoverEvent);
                    img.dispatchEvent(mouseenterEvent);
                }
            """,
                img_element,
            )

            # 等待下载按钮出现
            download_button = None
            for selector in DOWNLOAD_BUTTON:
                try:
                    download_button = await self.page.wait_for_selector(
                        selector, state="visible", timeout=1000
                    )
                    if download_button:
                        break
                except Exception:
                    continue

            if not download_button:
                return None

            # 多次尝试点击下载按钮（下载按钮可能未就绪，需要重试）
            download_timeout = 5000
            max_click_attempts = 6

            for attempt in range(max_click_attempts):
                try:
                    async with self.page.expect_download(
                        timeout=download_timeout
                    ) as download_info:
                        if click_method == "no_wait":
                            await download_button.click(no_wait_after=True)
                        elif click_method == "js":
                            await self.page.evaluate(
                                "(btn) => btn.click()", download_button
                            )
                        elif click_method == "force":
                            await download_button.click(force=True)
                        else:
                            await download_button.click()

                    download = await download_info.value

                    # 读取下载内容到内存
                    download_path = await download.path()
                    if download_path:
                        with open(download_path, "rb") as f:
                            image_bytes = f.read()
                        print(
                            f"  ✓ 通过下载按钮获取原图 ({len(image_bytes)/1024:.1f}KB) [点击方法: {click_method}, 尝试: {attempt + 1}/{max_click_attempts}]"
                        )
                        return image_bytes

                except Exception:
                    if attempt < max_click_attempts - 1:
                        print(
                            f"  ⚠ 下载按钮点击失败（尝试 {attempt + 1}/{max_click_attempts}），0.5秒后重试..."
                        )
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        print(f"  ⚠ 下载按钮点击失败（已尝试 {max_click_attempts} 次）")
                        return None

            return None

        except Exception:
            return None

    async def _download_via_hover_button(
        self, url: str, click_method: str = "no_wait"
    ) -> bytes | None:
        """
        通过 hover 触发下载按钮，下载到内存

        Args:
            url: 图片URL
            click_method: 点击方法
                - "no_wait": 使用 click(no_wait_after=True) (默认，推荐)
                - "js": JS 点击（最快但可能不稳定）
                - "force": 使用 click(force=True)
                - "normal": 普通 click()

        Returns:
            图片字节数据，失败返回 None
        """
        # 直接使用指定的点击方法（有重试机制兜底）
        return await self._try_download_with_method(url, click_method)

    async def _try_download_with_method(
        self, url: str, click_method: str
    ) -> bytes | None:
        """尝试使用指定的点击方法下载"""
        try:
            # 查找页面上src匹配的img元素
            images = await self.page.query_selector_all("img")
            target_img = None

            for img in images:
                src = await img.get_attribute("src")
                if src and src == url:
                    target_img = img
                    break

            if not target_img:
                return None

            # Hover 到图片上，触发下载按钮显示
            await self.page.evaluate(
                """
                (img) => {
                    const rect = img.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;

                    const mouseoverEvent = new MouseEvent('mouseover', {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    });

                    const mouseenterEvent = new MouseEvent('mouseenter', {
                        bubbles: false,
                        cancelable: false,
                        view: window,
                        clientX: x,
                        clientY: y
                    });

                    img.dispatchEvent(mouseoverEvent);
                    img.dispatchEvent(mouseenterEvent);
                }
            """,
                target_img,
            )

            # 等待下载按钮出现
            download_button = None
            for selector in DOWNLOAD_BUTTON:
                try:
                    download_button = await self.page.wait_for_selector(
                        selector, state="visible", timeout=1000
                    )
                    if download_button:
                        break
                except Exception:
                    continue

            if not download_button:
                return None

            # 根据点击方法选择不同的点击策略
            # 多次尝试点击下载按钮（下载按钮可能未就绪，需要重试）
            download_timeout = 5000
            max_click_attempts = 4  # 最多尝试4次点击

            for attempt in range(max_click_attempts):
                try:
                    async with self.page.expect_download(
                        timeout=download_timeout
                    ) as download_info:
                        if click_method == "no_wait":
                            # 方法1: 不等待导航完成（推荐）
                            await download_button.click(no_wait_after=True)
                        elif click_method == "js":
                            # 方法2: JS 点击（最快但可能不稳定）
                            await self.page.evaluate(
                                "(btn) => btn.click()", download_button
                            )
                        elif click_method == "force":
                            # 方法3: 强制点击，跳过可操作性检查
                            await download_button.click(force=True)
                        else:
                            # 方法4: 普通点击
                            await download_button.click()

                    download = await download_info.value

                    # 读取下载内容到内存
                    download_path = await download.path()
                    if download_path:
                        with open(download_path, "rb") as f:
                            image_bytes = f.read()
                        print(
                            f"  ✓ 通过下载按钮获取原图 ({len(image_bytes)/1024:.1f}KB) [点击方法: {click_method}, 尝试: {attempt + 1}/{max_click_attempts}]"
                        )
                        return image_bytes

                except Exception:
                    # 点击失败（弹出"无法下载"气泡），等待0.5秒后重试
                    if attempt < max_click_attempts - 1:
                        print(
                            f"  ⚠ 下载按钮点击失败（尝试 {attempt + 1}/{max_click_attempts}），0.5秒后重试..."
                        )
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        # 所有尝试都失败，返回 None 让调用者 fallback
                        print(
                            f"  ❌ 下载按钮点击失败（已尝试 {max_click_attempts} 次）"
                        )
                        return None

            return None

        except Exception:
            # 静默失败，让调用者回退到其他方法
            return None

    async def download_image(self, url: str, save_path: str) -> tuple[bool, str | None]:
        """
        下载图片到本地（通过hover显示下载按钮并点击）

        Args:
            url: 图片URL
            save_path: 保存路径

        Returns:
            (是否下载成功, SHA256摘要前16位)
        """
        return await self._do_download_image(url, save_path, silent=False)

    async def _do_download_image(
        self, url: str, save_path: str, silent: bool = False
    ) -> tuple[bool, str | None]:
        """
        下载图片的内部实现

        Args:
            url: 图片URL
            save_path: 保存路径
            silent: 是否静默模式（不打印日志）

        Returns:
            (是否下载成功, SHA256摘要前16位)
        """
        import hashlib
        import time

        if not silent:
            print("\n正在下载图片...")
            print(f"  URL: {url[:80]}...")
            print(f"  保存到: {save_path}")

        try:
            # 查找页面上src匹配的img元素
            find_start = time.time()
            images = await self.page.query_selector_all("img")
            target_img = None

            for img in images:
                src = await img.get_attribute("src")
                if src and src == url:
                    target_img = img
                    break

            if not target_img:
                if not silent:
                    print("  ❌ 未找到图片元素")
                return False, None

            if not silent:
                find_time = time.time() - find_start
                print(f"    ⏱ [定位图片] {find_time:.3f}s")

            # Hover到图片上，触发下载按钮显示（使用JavaScript模拟）
            if not silent:
                print("  悬停到图片上...")

            hover_start = time.time()
            # 使用JavaScript触发鼠标事件
            await self.page.evaluate(
                """
                (img) => {
                    const rect = img.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;

                    const mouseoverEvent = new MouseEvent('mouseover', {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    });

                    const mouseenterEvent = new MouseEvent('mouseenter', {
                        bubbles: false,
                        cancelable: false,
                        view: window,
                        clientX: x,
                        clientY: y
                    });

                    img.dispatchEvent(mouseoverEvent);
                    img.dispatchEvent(mouseenterEvent);
                }
            """,
                target_img,
            )

            await asyncio.sleep(2)

            # 查找下载按钮
            download_button = None
            for selector in DOWNLOAD_BUTTON:
                btns = await self.page.query_selector_all(selector)
                for btn in btns:
                    if await btn.is_visible():
                        download_button = btn
                        if not silent:
                            aria_label = await btn.get_attribute("aria-label")
                            hover_time = time.time() - hover_start
                            print(f"  ✓ 找到下载按钮: {aria_label}")
                            print(f"    ⏱ [hover触发] {hover_time:.3f}s")
                        break
                if download_button:
                    break

            if not download_button:
                if not silent:
                    print("  ❌ 未找到下载按钮，尝试使用fetch下载...")
                # 回退到fetch方法
                return await self._download_with_fetch(url, save_path, silent)

            # 设置下载路径
            save_file = Path(save_path)
            save_file.parent.mkdir(parents=True, exist_ok=True)

            # 等待下载完成的Promise
            download_start = time.time()
            async with self.page.expect_download() as download_info:
                await download_button.click()
                if not silent:
                    print("  ✓ 已点击下载按钮")

            download = await download_info.value

            # 保存文件并计算 SHA256
            download_path = await download.path()
            if download_path:
                with open(download_path, "rb") as f:
                    file_data = f.read()

                # 计算 SHA256 摘要（完整 base64url 格式，去除填充符号）
                hash_start = time.time()
                import base64

                sha256_hash = hashlib.sha256(file_data).digest()
                # 使用 base64url 编码（URL安全），并去除填充符号 '='
                file_hash = (
                    base64.urlsafe_b64encode(sha256_hash).decode("ascii").rstrip("=")
                )
                hash_time = time.time() - hash_start

                # 保存到目标路径
                save_start = time.time()
                with open(save_file, "wb") as f:
                    f.write(file_data)
                save_time = time.time() - save_start

                if not silent:
                    download_time = time.time() - download_start
                    file_size = len(file_data)
                    print(f"    ⏱ [下载] {download_time:.3f}s ({file_size/1024:.1f}KB)")
                    print(f"    ⏱ [SHA256计算] {hash_time:.3f}s")
                    print(f"    ⏱ [文件保存] {save_time:.3f}s")
                    print(f"  ✓ 图片已保存: {save_path}")

                return True, file_hash
            else:
                if not silent:
                    print("  ❌ 下载失败：无法获取文件")
                return False, None

        except Exception as e:
            if not silent:
                print(f"❌ 下载图片失败: {e}")
                import traceback

                traceback.print_exc()
            # 尝试回退方法
            return await self._download_with_fetch(url, save_path, silent)

    async def _download_with_fetch(
        self, url: str, save_path: str, silent: bool = False
    ) -> tuple[bool, str | None]:
        """使用 Playwright request API 下载（绕过 CORS，并发安全）"""
        import hashlib
        import time

        try:
            if not silent:
                print("  使用 Playwright request 下载...")

            # 使用 Playwright 的 request API，会自动带上浏览器的 cookies
            download_start = time.time()
            response = await self.page.request.get(url)

            if not response.ok:
                if not silent:
                    print(f"  ❌ 下载失败，HTTP状态: {response.status}")
                return False, None

            # 获取图片数据
            image_bytes = await response.body()
            download_time = time.time() - download_start

            if not silent:
                print(
                    f"    ⏱ [网络下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)"
                )

            # 计算 SHA256 摘要（完整 base64url 格式，去除填充符号）
            hash_start = time.time()
            import base64

            sha256_hash = hashlib.sha256(image_bytes).digest()
            # 使用 base64url 编码（URL安全），并去除填充符号 '='
            file_hash = (
                base64.urlsafe_b64encode(sha256_hash).decode("ascii").rstrip("=")
            )
            hash_time = time.time() - hash_start

            if not silent:
                print(f"    ⏱ [SHA256计算] {hash_time:.3f}s")

            # 保存到文件
            save_start = time.time()
            save_file = Path(save_path)
            save_file.parent.mkdir(parents=True, exist_ok=True)

            with open(save_file, "wb") as f:
                f.write(image_bytes)

            save_time = time.time() - save_start

            if not silent:
                print(f"    ⏱ [文件保存] {save_time:.3f}s")
                print(f"  ✓ 图片已保存: {save_path}")

            return True, file_hash

        except Exception as e:
            if not silent:
                print(f"  ❌ 下载失败: {e}")
                import traceback

                traceback.print_exc()
            return False, None
