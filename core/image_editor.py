"""
Gemini 图片编辑器

提供完整的图片编辑功能API
"""

import asyncio
from pathlib import Path
from typing import List, Optional

from .gemini_browser import GeminiBrowser


class GeminiImageEditor(GeminiBrowser):
    """Gemini图片编辑器 - 扩展自GeminiBrowser"""

    def __init__(
        self,
        account_id: int = 0,
        headless: bool = False,
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
            await asyncio.sleep(2)

        print("✓ 已在对话页面")

    async def click_image_generation_button(self):
        """点击图片生成按钮（适配中英文）"""
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
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.click(selector)
                    await asyncio.sleep(1)
                    print("✓ 图片生成功能已激活")
                    return True
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
                'div[contenteditable="true"]', state="visible", timeout=10000
            )

            if not input_box:
                print("❌ 未找到输入框")
                return False

            print("  ✓ 找到输入框，点击聚焦")
            await input_box.click()
            await asyncio.sleep(0.3)

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
                'img[src^="blob:"]',
                timeout=timeout * 1000,
                state="visible"
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
            await asyncio.sleep(0.5)  # 减少等待时间

            # 步骤2: 等待并点击菜单中的"上传文件"选项（使用结构化定位）
            print("  等待上传文件选项出现...")

            upload_option = None
            max_attempts = 10

            for attempt in range(max_attempts):
                await asyncio.sleep(0.2)  # 短暂等待

                # 方法1: 尝试通过菜单容器定位（更可靠）
                # 查找最近出现的菜单容器（通常是role="menu"或role="listbox"）
                menu_containers = await self.page.query_selector_all(
                    '[role="menu"], [role="listbox"], [role="dialog"]'
                )

                for container in menu_containers:
                    try:
                        if not await container.is_visible():
                            continue

                        # 在菜单容器内查找按钮
                        buttons_in_menu = await container.query_selector_all("button")

                        for btn in buttons_in_menu:
                            if not await btn.is_visible():
                                continue

                            # 检查是否有file input相关的属性或数据
                            # 通常上传文件按钮会有特定的data属性或类名
                            aria_label = await btn.get_attribute("aria-label") or ""
                            text = await btn.text_content() or ""

                            # 检查关键词
                            combined = (aria_label + text).lower()
                            upload_keywords = [
                                "上传文件",
                                "upload file",
                                "upload files",
                                "上传",
                                "upload",
                            ]

                            if any(
                                keyword.lower() in combined
                                for keyword in upload_keywords
                            ):
                                upload_option = btn
                                print("  ✓ 在菜单中找到上传选项")
                                break

                        if upload_option:
                            break
                    except Exception:
                        continue

                # 方法2: 如果方法1失败，回退到全局搜索但优化检测
                if not upload_option:
                    all_buttons = await self.page.query_selector_all("button")

                    for btn in all_buttons:
                        try:
                            if not await btn.is_visible():
                                continue

                            # 检查按钮的边界框，确保它在视口内且大小合理
                            bbox = await btn.bounding_box()
                            if not bbox or bbox["width"] < 10 or bbox["height"] < 10:
                                continue

                            aria_label = await btn.get_attribute("aria-label") or ""
                            text = await btn.text_content() or ""
                            combined = (aria_label + text).lower()

                            upload_keywords = [
                                "上传文件",
                                "upload file",
                                "upload files",
                            ]

                            if any(
                                keyword.lower() in combined
                                for keyword in upload_keywords
                            ):
                                upload_option = btn
                                print("  ✓ 找到上传选项（全局搜索）")
                                break
                        except Exception:
                            continue

                if upload_option:
                    break

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

            # 验证上传成功（检查blob URL）- 优化重试逻辑
            print("  等待图片加载...")
            for attempt in range(5):
                await asyncio.sleep(1)

                images = await self.page.query_selector_all("img")
                for img in images:
                    src = await img.get_attribute("src")
                    if src and "blob:" in src:
                        print(f"✓ 图片上传成功: {src[:80]}...")
                        return True

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
                'div[contenteditable="true"]', state="visible", timeout=10000
            )

            if prompt_input:
                print("  ✓ 输入框就绪，立即输入")
                await prompt_input.fill(prompt)
                await asyncio.sleep(0.5)
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
            # 中英文提交按钮选择器
            submit_selectors = [
                'button[aria-label*="发送"]',  # 中文
                'button[aria-label*="Send"]',  # 英文
                'button[aria-label*="submit"]',  # 英文备选
            ]

            submit_button = None
            for selector in submit_selectors:
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
        等待图片生成完成（通过检测加载动画结束）
        使用对话容器定位来避免计数页面其他位置的图片

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否生成成功
        """
        print(f"\n等待图片生成完成（最多{timeout}秒）...")

        start_time = asyncio.get_event_loop().time()

        # 策略1: 检测生成按钮是否重新可用（生成中会禁用）
        # 策略2: 检测最新对话容器内是否有新的 googleusercontent 图片出现
        # 策略3: 超时保护

        last_image_count = 0
        stable_count = 0  # 图片数量稳定的次数

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                print(f"⚠ 等待超时（{timeout}秒），停止等待")
                return False

            # 尝试定位最新的对话容器
            container = None
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
                        break
                except Exception:
                    continue

            # 在容器内（如果找到）或全局搜索图片
            if container:
                images = await container.query_selector_all("img")
            else:
                images = await self.page.query_selector_all("img")

            current_count = 0

            for img in images:
                src = await img.get_attribute("src")
                if src and "googleusercontent" in src and "/a/ACg8oc" not in src:
                    current_count += 1

            # 如果图片数量稳定（连续3次检查数量相同），认为生成完成
            if current_count > 0:
                if current_count == last_image_count:
                    stable_count += 1
                    if stable_count >= 3:
                        print(f"✓ 检测到 {current_count} 张生成的图片（已稳定）")
                        return True
                else:
                    stable_count = 0
                    print(f"  检测到 {current_count} 张图片（等待稳定...）")

            last_image_count = current_count

            # 每2秒检查一次
            await asyncio.sleep(2)

    async def get_generated_images(self) -> List[str]:
        """
        获取生成的图片URL列表（去重，排除头像）
        通过定位最新的对话消息容器来精确获取图片

        注意：不等待URL更新，因为我们优先使用hover按钮下载（不依赖URL）

        Returns:
            图片URL列表（已去重，排除头像）
        """
        # 策略：定位最新的模型回复容器
        # Gemini 的 DOM 结构：message-content > model-response > response-container
        print("\n正在定位最新的对话回复...")

        # 尝试多种选择器策略
        container_selectors = [
            # 方案1: 直接找所有 model-response 容器，取最后一个
            "model-response",
            # 方案2: 通过 message-content 找
            "message-content model-response",
            # 方案3: 通过 response-container
            "response-container",
        ]

        container = None
        for selector in container_selectors:
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

            # 过滤条件：
            # 1. googleusercontent域名
            # 2. 不是头像（排除ACg8oc开头的URL和包含"个人资料"、"照片"等的alt）
            if src and "googleusercontent" in src:
                # 排除头像URL
                if "/a/ACg8oc" in src:
                    continue
                if alt and any(
                    keyword in alt
                    for keyword in ["个人资料", "照片", "profile", "photo"]
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

    async def download_image_as_webp(
        self, url: str, save_path: str, lossless: bool = True
    ) -> tuple[bool, str | None]:
        """
        下载图片并转换为 WebP 格式（更小的文件体积）

        优先使用 hover 下载按钮获取高质量原图，失败则回退到 page.request.get

        Args:
            url: 图片URL
            save_path: 保存路径（会自动改为.webp扩展名）
            lossless: 是否使用无损压缩，默认 True（推荐）

        Returns:
            (是否下载成功, SHA256摘要前16位)
        """
        import time
        import hashlib

        # 确保保存路径使用 .webp 扩展名
        save_path_obj = Path(save_path)
        save_path_webp = str(save_path_obj.with_suffix(".webp"))

        try:
            from io import BytesIO
            from PIL import Image

            image_bytes = None

            # 方法1: 尝试通过 hover 下载按钮获取高质量原图
            download_start = time.time()
            image_bytes = await self._download_via_hover_button(url)
            if image_bytes:
                download_time = time.time() - download_start
                print(f"    ⏱ [hover下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)")

            # 方法2: 回退到 page.request.get
            if not image_bytes:
                print("  回退到 request API 下载...")
                download_start = time.time()
                response = await self.page.request.get(url)
                if response.ok:
                    image_bytes = await response.body()
                    download_time = time.time() - download_start
                    print(f"    ⏱ [request下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)")
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
            file_hash = base64.urlsafe_b64encode(sha256_hash).decode('ascii').rstrip('=')
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
            print(f"    原始: {original_size/1024:.1f}KB → WebP: {webp_size/1024:.1f}KB (压缩率: {compression:.1f}%)")

            return True, file_hash

        except ImportError:
            print("  ❌ 需要安装 Pillow 库: pip install Pillow")
            return False, None
        except Exception as e:
            print(f"❌ WebP下载失败: {e}")
            import traceback
            traceback.print_exc()
            return False, None

    async def _download_via_hover_button(self, url: str) -> bytes | None:
        """
        通过 hover 触发下载按钮，下载到内存

        Args:
            url: 图片URL

        Returns:
            图片字节数据，失败返回 None
        """
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

            await asyncio.sleep(1)

            # 查找下载按钮
            download_button_selectors = [
                'button[aria-label*="下载"]',
                'button[aria-label*="Download"]',
                'button[aria-label*="保存"]',
                'button[aria-label*="Save"]',
            ]

            download_button = None
            for selector in download_button_selectors:
                btns = await self.page.query_selector_all(selector)
                for btn in btns:
                    if await btn.is_visible():
                        download_button = btn
                        break
                if download_button:
                    break

            if not download_button:
                return None

            # 点击下载按钮并拦截下载
            async with self.page.expect_download() as download_info:
                await download_button.click()

            download = await download_info.value

            # 读取下载内容到内存
            download_path = await download.path()
            if download_path:
                with open(download_path, "rb") as f:
                    image_bytes = f.read()
                print(f"  ✓ 通过下载按钮获取原图 ({len(image_bytes)/1024:.1f}KB)")
                return image_bytes

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

    async def _do_download_image(self, url: str, save_path: str, silent: bool = False) -> tuple[bool, str | None]:
        """
        下载图片的内部实现

        Args:
            url: 图片URL
            save_path: 保存路径
            silent: 是否静默模式（不打印日志）

        Returns:
            (是否下载成功, SHA256摘要前16位)
        """
        import time
        import hashlib

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

            # 查找下载按钮（可能有多种aria-label）
            download_button_selectors = [
                'button[aria-label*="下载"]',
                'button[aria-label*="Download"]',
                'button[aria-label*="保存"]',
                'button[aria-label*="Save"]',
            ]

            download_button = None
            for selector in download_button_selectors:
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
                file_hash = base64.urlsafe_b64encode(sha256_hash).decode('ascii').rstrip('=')
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

    async def _download_with_fetch(self, url: str, save_path: str, silent: bool = False) -> tuple[bool, str | None]:
        """使用 Playwright request API 下载（绕过 CORS，并发安全）"""
        import time
        import hashlib

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
                print(f"    ⏱ [网络下载] {download_time:.3f}s ({len(image_bytes)/1024:.1f}KB)")

            # 计算 SHA256 摘要（完整 base64url 格式，去除填充符号）
            hash_start = time.time()
            import base64
            sha256_hash = hashlib.sha256(image_bytes).digest()
            # 使用 base64url 编码（URL安全），并去除填充符号 '='
            file_hash = base64.urlsafe_b64encode(sha256_hash).decode('ascii').rstrip('=')
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

    async def edit_image(
        self,
        input_image: str,
        prompt: str,
        output_dir: str = "output",
        wait_time: int = 30,
        upload_method: str = "paste",
        upload_timeout: int = 60,
        output_format: str = "webp",
        webp_lossless: bool = True,
    ) -> Optional[List[str]]:
        """
        完整的图片编辑流程

        Args:
            input_image: 输入图片路径
            prompt: 编辑指令
            output_dir: 输出目录
            wait_time: 等待生成的时间（秒）
            upload_method: 上传方式 - "paste"（粘贴，推荐）、"button"（按钮）、"manual"（手动）
            upload_timeout: 手动上传模式的超时时间（秒）
            output_format: 输出格式 - "webp"（推荐，文件小）、"png"（原始格式）
            webp_lossless: WebP 无损压缩，默认 True（推荐）；False 为有损压缩 quality=80

        Returns:
            保存的图片路径列表，失败返回None
        """
        print("=" * 60)
        print("开始图片编辑流程")
        print("=" * 60)
        print(f"输入图片: {input_image}")
        print(f"编辑指令: {prompt}")
        print(f"输出目录: {output_dir}")
        print(f"上传方式: {upload_method}")

        try:
            # 1. 确保在新对话页面
            await self.navigate_to_new_chat()

            # 2. 激活图片生成功能
            if not await self.click_image_generation_button():
                return None

            # 3. 上传图片
            if upload_method == "paste":
                if not await self.upload_image_by_paste(input_image):
                    return None
            elif upload_method == "button":
                if not await self.upload_image(input_image, manual=False):
                    return None
            elif upload_method == "manual":
                if not await self.upload_image(
                    input_image, manual=True, timeout=upload_timeout
                ):
                    return None
            else:
                print(f"❌ 不支持的上传方式: {upload_method}")
                return None

            # 4. 输入prompt
            if not await self.input_prompt(prompt):
                return None

            # 5. 提交生成
            if not await self.submit_generation():
                return None

            # 6. 等待生成完成
            await self.wait_for_generation(wait_time)

            # 7. 获取生成的图片
            image_urls = await self.get_generated_images()

            if not image_urls:
                print("❌ 未找到生成的图片")
                return None

            # 8. 下载所有生成的图片
            output_paths = []
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            for i, url in enumerate(image_urls):
                if output_format == "webp":
                    save_path = output_path / f"generated_{i+1}.webp"
                    if await self.download_image_as_webp(
                        url, str(save_path), lossless=webp_lossless
                    ):
                        output_paths.append(str(save_path))
                else:  # png
                    save_path = output_path / f"generated_{i+1}.png"
                    if await self.download_image(url, str(save_path)):
                        output_paths.append(str(save_path))

            print("\n" + "=" * 60)
            print(f"✓ 图片编辑完成！共生成 {len(output_paths)} 张图片")
            print("=" * 60)

            for path in output_paths:
                print(f"  {path}")

            return output_paths

        except Exception as e:
            print(f"\n❌ 图片编辑流程失败: {e}")
            import traceback

            traceback.print_exc()
            return None


async def main():
    """示例：使用图片编辑器"""
    editor = GeminiImageEditor(account_id=0, headless=False)

    try:
        # 启动浏览器
        await editor.launch()

        # 编辑图片
        test_image = "test/lamp.webp"  # 替换为你的测试图片
        test_prompt = "把这个灯变成蓝色"

        result = await editor.edit_image(
            input_image=test_image,
            prompt=test_prompt,
            output_dir="output/test1",
            wait_time=30,
        )

        if result:
            print(f"\n成功！生成了 {len(result)} 张图片")
        else:
            print("\n失败！")

    finally:
        await editor.close()


if __name__ == "__main__":
    asyncio.run(main())
