"""
Gemini 图片编辑器 - 统一的浏览器自动化图片编辑工具

功能：
- 浏览器会话管理（无头模式）
- 图片上传（粘贴/点击方式）
- 图片生成和下载
- 模型选择（Pro/Fast）
- 临时会话支持
"""

import asyncio
import base64
import hashlib
import json
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Literal, Optional
from urllib.parse import urlparse, urlunparse

from PIL import Image
from playwright.async_api import BrowserContext, Page, async_playwright

from .browser import (
    AGREE_BUTTON,
    DEFAULT_PERMISSIONS,
    DEFAULT_VIEWPORT,
    DOWNLOAD_BUTTON,
    IMAGE_GEN_DESELECT,
    IMAGE_GEN_OPTION,
    INPUT_BOX,
    MAIN_MENU_BUTTON,
    MODEL_MENU_BUTTON,
    MODEL_OPTION_FAST,
    MODEL_OPTION_PRO,
    RESPONSE_CONTAINER,
    SUBMIT_BUTTON,
    TEMP_CHAT_BUTTON,
    TEMP_CHAT_CARD,
    TEMP_CHAT_TITLE,
    TOOLS_BUTTON,
    UPLOAD_MENU_BUTTON,
    get_launch_args,
    get_model_keywords,
    is_generated_image,
)
from .watermark_remover import WatermarkRemover


class GeminiEditor:
    """Gemini 图片编辑器"""

    def __init__(
        self,
        account_id: int = 0,
        proxy: Optional[str] = None,
        user_data_dir: Optional[Path] = None,
        enable_logging: bool = False,
    ):
        self.account_id = account_id
        self.proxy = proxy
        self.enable_logging = enable_logging
        self.event_log: List[dict] = []

        # 数据目录
        self.base_dir = Path(__file__).parent.parent / "data"
        data_dir = Path("/app/data") if Path("/app/data").exists() else self.base_dir

        if user_data_dir:
            self.user_data_dir = Path(user_data_dir) if isinstance(user_data_dir, str) else user_data_dir
        else:
            self.user_data_dir = data_dir / "browser_data" / str(account_id)

        self.playwright = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.default_timeout = 60000

    # =========================================================================
    # 浏览器生命周期
    # =========================================================================

    async def launch(self, timeout: int = 60000) -> Page:
        """启动浏览器并访问 Gemini"""
        if not self.user_data_dir.exists():
            print(f"创建浏览器数据目录: {self.user_data_dir}")
            self.user_data_dir.mkdir(parents=True, exist_ok=True)

        print("=" * 60)
        print(f"启动 Gemini 编辑器 - 账户 {self.account_id}")
        print("=" * 60)
        print(f"数据目录: {self.user_data_dir}")

        self.playwright = await async_playwright().start()
        launch_args = get_launch_args(proxy=self.proxy)

        if self.proxy:
            print(f"使用代理: {self.proxy}")

        self.context = await self.playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=True,
            viewport=DEFAULT_VIEWPORT,
            args=launch_args,
            permissions=DEFAULT_PERMISSIONS,
        )

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        print("正在访问 Gemini...")
        await self.page.goto("https://gemini.google.com/app", wait_until="load", timeout=timeout)

        title = await self.page.title()
        print(f"页面已加载: {title}")

        if self.enable_logging:
            self._setup_event_listeners()

        return self.page

    async def close(self):
        """关闭浏览器"""
        if self.context:
            await self.context.close()
            print("浏览器已关闭")
        if self.playwright:
            await self.playwright.stop()

    def _setup_event_listeners(self):
        """设置页面事件监听"""
        self.page.on(
            "framenavigated",
            lambda frame: self._log_event("navigation", {"url": frame.url}),
        )

    def _log_event(self, event_type: str, data: dict):
        """记录事件"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "data": data,
        }
        self.event_log.append(log_entry)
        if self.enable_logging:
            print(f"[EVENT] {event_type}: {data.get('url', '')[:100]}")

    # =========================================================================
    # 页面环境准备
    # =========================================================================

    async def start_new_chat(self) -> bool:
        """开启新对话（Ctrl+Shift+O）"""
        print("开启新对话...")
        try:
            current_url = self.page.url
            is_new_chat = bool(re.match(r"^https://[^/]+/app(?:[?#].*)?$", current_url))

            if is_new_chat:
                input_box = await self.page.query_selector('div[contenteditable="true"]')
                if input_box:
                    print("已在新对话页面，跳过刷新")
                    return True

            await self.page.keyboard.press("Control+Shift+O")
            await self.page.wait_for_selector('div[contenteditable="true"]', timeout=5000)

            if "/app" in self.page.url:
                print(f"新对话已开启: {self.page.url}")
                return True

            await self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            await self.page.wait_for_selector('div[contenteditable="true"]', timeout=5000)
            return True

        except Exception as e:
            print(f"开启新对话失败: {e}")
            return False

    async def ensure_model_selection(self, model: Literal["Pro", "Fast"] = "Fast") -> bool:
        """确保选择了指定的模型"""
        print(f"选择模型: {model}")
        try:
            await self.page.wait_for_selector(MODEL_MENU_BUTTON, timeout=5000, state="attached")
            menu_button = self.page.locator(MODEL_MENU_BUTTON)
            button_text = await menu_button.inner_text()

            fast_keywords = get_model_keywords("Fast")
            pro_keywords = get_model_keywords("Pro")

            is_fast = any(kw in button_text or kw.lower() in button_text.lower() for kw in fast_keywords)
            is_pro = any(kw in button_text or kw.lower() in button_text.lower() for kw in pro_keywords)

            if (model == "Fast" and is_fast) or (model == "Pro" and is_pro):
                print(f"已是 {model} 模型")
                return True

            target_selectors = MODEL_OPTION_FAST if model == "Fast" else MODEL_OPTION_PRO

            for attempt in range(3):
                await menu_button.click(no_wait_after=True)
                for selector in target_selectors:
                    try:
                        option = await self.page.wait_for_selector(selector, timeout=1000, state="visible")
                        if option:
                            await option.click(no_wait_after=True)
                            await self.page.wait_for_timeout(300)
                            return True
                    except Exception:
                        continue

            return False
        except Exception as e:
            print(f"模型选择失败: {e}")
            return False

    async def activate_image_generation(self) -> bool:
        """激活图片生成功能"""
        print("激活图片生成功能...")
        try:
            # 检查是否已激活
            deselect = await self.page.query_selector(IMAGE_GEN_DESELECT)
            if deselect:
                label = await deselect.get_attribute("aria-label")
                if label and ("图片" in label or "image" in label.lower()):
                    print("图片生成已激活")
                    return True

            # 点击 Tools 菜单
            tools_btn = None
            for selector in TOOLS_BUTTON:
                try:
                    tools_btn = await self.page.wait_for_selector(selector, state="visible", timeout=5000)
                    if tools_btn:
                        break
                except Exception:
                    continue

            if not tools_btn:
                print("未找到 Tools 菜单")
                return False

            await tools_btn.click(no_wait_after=True)

            # 点击图片生成选项
            for selector in IMAGE_GEN_OPTION:
                try:
                    option = await self.page.wait_for_selector(selector, timeout=3000, state="visible")
                    if option:
                        await option.evaluate("el => el.click()")
                        return True
                except Exception:
                    continue

            return False
        except Exception as e:
            print(f"激活图片生成失败: {e}")
            return False

    async def verify_image_generation_activated(self) -> bool:
        """验证图片生成功能是否已激活"""
        try:
            deselect = await self.page.wait_for_selector(IMAGE_GEN_DESELECT, timeout=3000, state="visible")
            if deselect:
                label = await deselect.get_attribute("aria-label")
                if label and ("图片" in label or "image" in label.lower()):
                    return True
            return False
        except Exception:
            return False

    async def prepare_environment(self, model: Literal["Pro", "Fast"] = "Fast", temporary_chat: bool = False) -> bool:
        """准备页面环境（新对话 + 激活图片生成 + 选择模型）"""
        try:
            if not await self.start_new_chat():
                print("开启新对话失败")

            if not await self.activate_image_generation():
                print("激活图片生成失败，继续...")
                # return False
            

            await self.ensure_model_selection(model)

            if not await self.verify_image_generation_activated():
                print("图片生成验证失败，继续...")
                # return False

            print("页面环境准备完成")
            return True
        except Exception as e:
            print(f"页面环境准备失败: {e}")
            return False

    async def prepare_for_generation(
        self,
        input_image: str,
        prompt: str,
        model: Literal["Pro", "Fast"] = "Fast",
        temporary_chat: bool = False,
        max_retries: int = 2,
    ) -> bool:
        """准备图片生成（上传图片、输入文本，但不提交）"""
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    print(f"重试准备流程（第 {attempt} 次）...")

                if not await self.prepare_environment(model, temporary_chat):
                    return False

                if not await self.upload_image_by_paste(input_image):
                    print("图片上传失败")
                    return False

                if not await self.input_prompt(prompt):
                    if await self._dismiss_consent_dialog():
                        continue
                    return False

                return True
            except Exception as e:
                print(f"准备过程出错: {e}")
                if await self._dismiss_consent_dialog():
                    continue
                return False

        return False

    async def submit_generation(self) -> bool:
        """submit 的别名"""
        return await self.submit()

    # =========================================================================
    # 图片上传
    # =========================================================================

    async def upload_image_by_paste(self, image_path: str) -> bool:
        """通过粘贴方式上传图片"""
        print(f"上传图片（粘贴）: {image_path}")
        image_file = Path(image_path)
        if not image_file.exists():
            print(f"图片不存在: {image_path}")
            return False

        try:
            input_box = await self.page.wait_for_selector(INPUT_BOX, state="visible", timeout=10000)
            if not input_box:
                return False

            await input_box.click()

            with open(image_file, "rb") as f:
                image_data = f.read()

            image_base64 = base64.b64encode(image_data).decode()

            suffix = image_file.suffix.lower()
            mime_type = {"jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(suffix, "image/webp")
            file_ext = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png"}.get(suffix, ".webp")

            result = await self.page.evaluate(
                """
                async (args) => {
                    const [imageBase64, mimeType, fileExt] = args;
                    try {
                        const byteCharacters = atob(imageBase64);
                        const byteNumbers = new Array(byteCharacters.length);
                        for (let i = 0; i < byteCharacters.length; i++) {
                            byteNumbers[i] = byteCharacters.charCodeAt(i);
                        }
                        const byteArray = new Uint8Array(byteNumbers);
                        const blob = new Blob([byteArray], { type: mimeType });
                        const file = new File([blob], "image" + fileExt, { type: mimeType });
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(file);
                        const target = document.querySelector('div[contenteditable="true"]');
                        if (!target) return { success: false };
                        const pasteEvent = new ClipboardEvent('paste', {
                            bubbles: true, cancelable: true, clipboardData: dataTransfer
                        });
                        target.focus();
                        target.dispatchEvent(pasteEvent);
                        return { success: true };
                    } catch (e) {
                        return { success: false };
                    }
                }
            """,
                [image_base64, mime_type, file_ext],
            )
            print("图片粘贴上传完成")

            return result.get("success", False)
        except Exception as e:
            print(f"粘贴上传失败: {e}")
            return False

    async def _dismiss_consent_dialog(self) -> bool:
        """关闭同意弹窗"""
        try:
            for selector in AGREE_BUTTON:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    return True
            return False
        except Exception:
            return False

    # =========================================================================
    # 输入和提交
    # =========================================================================

    async def input_prompt(self, prompt: str) -> bool:
        """输入编辑指令"""
        print(f"输入: {prompt}")
        try:
            input_box = await self.page.wait_for_selector(INPUT_BOX, state="visible", timeout=10000)
            if input_box:
                await input_box.fill(prompt)
                return True
            return False
        except Exception as e:
            print(f"输入失败: {e}")
            return False

    async def submit(self) -> bool:
        """提交生成请求"""
        print("提交请求...")
        try:
            for selector in SUBMIT_BUTTON:
                try:
                    btn = await self.page.wait_for_selector(selector, state="visible", timeout=3000)
                    if btn:
                        await btn.click()
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            print(f"提交失败: {e}")
            return False

    # =========================================================================
    # 等待和获取结果
    # =========================================================================

    async def wait_for_generation(self, timeout: int = 60) -> bool:
        """等待图片生成完成"""
        print(f"等待生成（最多 {timeout} 秒）...")
        try:
            await self.page.wait_for_function(
                """
                () => {
                    const selectors = ['model-response', 'response-container'];
                    for (const sel of selectors) {
                        const containers = document.querySelectorAll(sel);
                        if (containers.length > 0) {
                            const container = containers[containers.length - 1];
                            const images = container.querySelectorAll('img');
                            for (const img of images) {
                                const src = img.src || '';
                                if (src.includes('googleusercontent') && !src.includes('/a/ACg8oc')) {
                                    return true;
                                }
                            }
                        }
                    }
                    return false;
                }
                """,
                timeout=timeout * 1000,
            )
            print("图片生成完成")
            return True
        except Exception:
            print(f"等待超时（{timeout}秒）")
            return False

    async def get_generated_image_count(self) -> int:
        """获取生成的图片数量"""
        for selector in RESPONSE_CONTAINER:
            try:
                containers = await self.page.query_selector_all(selector)
                if containers:
                    container = containers[-1]
                    images = await container.query_selector_all("img")
                    count = 0
                    for img in images:
                        src = await img.get_attribute("src")
                        if is_generated_image(src):
                            count += 1
                    if count > 0:
                        return count
            except Exception:
                continue
        return 0

    # =========================================================================
    # 下载图片
    # =========================================================================

    async def download_image_by_index(
        self,
        index: int,
        save_path: str,
        output_format: str = "webp",
        lossless: bool = True,
        remove_watermark: bool = True,
    ) -> tuple[bool, Optional[str]]:
        """按索引下载生成的图片"""
        # 找到目标图片
        target_img = None
        for selector in RESPONSE_CONTAINER:
            try:
                containers = await self.page.query_selector_all(selector)
                if containers:
                    container = containers[-1]
                    images = await container.query_selector_all("img")
                    generated = [img for img in images if is_generated_image(await img.get_attribute("src"))]
                    if index < len(generated):
                        target_img = generated[index]
                        break
            except Exception:
                continue

        if not target_img:
            print(f"未找到索引 {index} 的图片")
            return False, None

        # 尝试通过 hover 下载按钮获取原图
        print(f"下载图片 {index + 1}...")
        image_bytes = await self._download_via_hover(target_img)

        if not image_bytes:
            # 回退到 request API
            url = await target_img.get_attribute("src")
            response = await self.page.request.get(url)
            if response.ok:
                image_bytes = await response.body()
            else:
                print(f"下载失败: HTTP {response.status}")
                return False, None

        # 保存图片
        return await self._save_image(image_bytes, save_path, output_format, lossless, remove_watermark)

    async def _download_via_hover(self, img_element) -> Optional[bytes]:
        """通过 hover 触发下载按钮获取原图"""
        try:
            await self.page.evaluate(
                """
                (img) => {
                    const rect = img.getBoundingClientRect();
                    const x = rect.left + rect.width / 2;
                    const y = rect.top + rect.height / 2;
                    img.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, clientX: x, clientY: y }));
                    img.dispatchEvent(new MouseEvent('mouseenter', { bubbles: false, clientX: x, clientY: y }));
                }
            """,
                img_element,
            )

            download_btn = None
            for selector in DOWNLOAD_BUTTON:
                try:
                    download_btn = await self.page.wait_for_selector(selector, state="visible", timeout=1000)
                    if download_btn:
                        break
                except Exception:
                    continue

            if not download_btn:
                return None

            for attempt in range(4):
                try:
                    async with self.page.expect_download(timeout=5000) as download_info:
                        await download_btn.click(no_wait_after=True)
                    download = await download_info.value
                    download_path = await download.path()
                    if download_path:
                        with open(download_path, "rb") as f:
                            return f.read()
                except Exception:
                    if attempt < 3:
                        await asyncio.sleep(0.5)
                    continue

            return None
        except Exception:
            return None

    async def _download_via_hover_button(self, url: str) -> Optional[bytes]:
        """通过 URL 找到图片并 hover 下载（browser_pool 兼容）"""
        try:
            images = await self.page.query_selector_all("img")
            for img in images:
                src = await img.get_attribute("src")
                if src and src == url:
                    return await self._download_via_hover(img)
            return None
        except Exception:
            return None

    async def _save_image(
        self,
        image_bytes: bytes,
        save_path: str,
        output_format: str = "webp",
        lossless: bool = True,
        remove_watermark: bool = True,
    ) -> tuple[bool, Optional[str]]:
        """保存图片并返回文件哈希"""
        try:
            img = Image.open(BytesIO(image_bytes))

            if remove_watermark:
                img = WatermarkRemover.remove_watermark(img, watermark_size=None, verbose=False)

            # 转换格式
            output = BytesIO()
            if output_format == "webp":
                save_path = str(Path(save_path).with_suffix(".webp"))
                img.save(output, "WEBP", lossless=lossless)
            else:
                img.save(output, output_format.upper())

            data = output.getvalue()

            # 计算哈希
            file_hash = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")

            # 保存
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(data)

            print(f"已保存: {save_path} ({len(data)/1024:.1f}KB)")
            return True, file_hash

        except Exception as e:
            print(f"保存失败: {e}")
            return False, None

    # =========================================================================
    # 高级编辑流程
    # =========================================================================

    async def edit_image(
        self,
        input_image: str,
        prompt: str,
        output_dir: str = "output",
        model: Literal["Pro", "Fast"] = "Fast",
        output_format: str = "webp",
        webp_lossless: bool = True,
    ) -> Optional[List[str]]:
        """
        完整的图片编辑流程

        Args:
            input_image: 输入图片路径
            prompt: 编辑指令
            output_dir: 输出目录
            model: 使用的模型
            output_format: 输出格式
            webp_lossless: WebP 无损压缩

        Returns:
            生成图片的路径列表
        """
        total_start = time.time()

        print("=" * 60)
        print("Gemini 图片编辑")
        print("=" * 60)
        print(f"输入: {input_image}")
        print(f"指令: {prompt}")
        print(f"模型: {model}")

        try:
            # 1. 准备环境
            if not await self.prepare_environment(model):
                return None

            # 2. 上传图片
            if not await self.upload_image_by_paste(input_image):
                print("图片上传失败")
                return None

            # 3. 输入指令
            if not await self.input_prompt(prompt):
                if await self._dismiss_consent_dialog():
                    if not await self.input_prompt(prompt):
                        return None
                else:
                    return None

            # 4. 提交
            if not await self.submit():
                return None

            # 5. 等待生成
            await self.wait_for_generation(timeout=120)

            # 6. 获取图片数量
            count = await self.get_generated_image_count()
            if count == 0:
                print("未找到生成的图片")
                return None

            # 7. 下载图片
            output_path = Path(output_dir) / datetime.now().strftime("%Y%m%d")
            output_path.mkdir(parents=True, exist_ok=True)

            result_paths = []
            for i in range(count):
                temp_path = output_path / f"temp_{i}.{output_format}"
                success, file_hash = await self.download_image_by_index(
                    i, str(temp_path), output_format, webp_lossless
                )
                if success and file_hash:
                    final_path = output_path / f"{file_hash}.{output_format}"
                    temp_path.rename(final_path)
                    result_paths.append(str(final_path))

            print("=" * 60)
            print(f"完成！生成 {len(result_paths)} 张图片，耗时 {time.time() - total_start:.1f}s")
            print("=" * 60)

            # 预热下次环境
            await self.prepare_environment(model)

            return result_paths if result_paths else None

        except Exception as e:
            print(f"编辑流程出错: {e}")
            import traceback
            traceback.print_exc()
            return None


# 兼容性别名
GeminiBrowser = GeminiEditor
GeminiImageEditor = GeminiEditor
EnhancedGeminiImageEditor = GeminiEditor

