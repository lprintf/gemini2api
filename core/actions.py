"""
Gemini 原子动作 - 纯函数化的浏览器自动化操作
"""

import asyncio
import base64
import hashlib
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from PIL import Image
from playwright.async_api import Page

from .gemini import (
    AGREE_BUTTON,
    DOWNLOAD_BUTTON,
    IMAGE_GEN_DESELECT,
    IMAGE_GEN_OPTION,
    INPUT_BOX,
    MODEL_MENU_BUTTON,
    MODEL_OPTION_FAST,
    MODEL_OPTION_PRO,
    RESPONSE_CONTAINER,
    SUBMIT_BUTTON,
    TOOLS_BUTTON,
    get_model_keywords,
    is_generated_image,
)
from .watermark_remover import WatermarkRemover


# =========================================================================
# 环境准备动作
# =========================================================================


async def start_new_chat(page: Page) -> bool:
    """开启新对话（Ctrl+Shift+O）"""
    print("开启新对话...")
    try:
        current_url = page.url
        is_new_chat = bool(re.match(r"^https://[^/]+/app(?:[?#].*)?$", current_url))

        if is_new_chat:
            input_box = await page.query_selector('div[contenteditable="true"]')
            if input_box:
                print("已在新对话页面，跳过刷新")
                return True

        await page.keyboard.press("Control+Shift+O")
        try:
            await page.wait_for_selector('div[contenteditable="true"]', timeout=5000)
        except:
            pass

        if "/app" in page.url:
            print(f"新对话已开启: {page.url}")
            return True

        await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
        await page.wait_for_selector('div[contenteditable="true"]', timeout=5000)
        return True

    except Exception as e:
        print(f"开启新对话失败: {e}")
        return False


async def ensure_model_selection(page: Page, model: Literal["Pro", "Fast"] = "Fast") -> bool:
    """确保选择了指定的模型"""
    print(f"选择模型: {model}")
    try:
        await page.wait_for_selector(MODEL_MENU_BUTTON, timeout=5000, state="attached")
        menu_button = page.locator(MODEL_MENU_BUTTON)
        button_text = await menu_button.inner_text()

        fast_keywords = get_model_keywords("Fast")
        pro_keywords = get_model_keywords("Pro")

        is_fast = any(
            kw in button_text or kw.lower() in button_text.lower() for kw in fast_keywords
        )
        is_pro = any(
            kw in button_text or kw.lower() in button_text.lower() for kw in pro_keywords
        )

        if (model == "Fast" and is_fast) or (model == "Pro" and is_pro):
            print(f"已是 {model} 模型")
            return True

        target_selectors = MODEL_OPTION_FAST if model == "Fast" else MODEL_OPTION_PRO

        for _ in range(3):
            await menu_button.click(no_wait_after=True)
            for selector in target_selectors:
                try:
                    option = await page.wait_for_selector(selector, timeout=1000, state="visible")
                    if option:
                        await option.click(no_wait_after=True)
                        await page.wait_for_timeout(300)
                        return True
                except Exception:
                    continue

        return False
    except Exception as e:
        print(f"模型选择失败: {e}")
        return False


async def is_image_generation_activated(page: Page, wait: bool = False, timeout: int = 3000) -> bool:
    """检查图片生成功能是否已激活"""
    try:
        if wait:
            deselect = await page.wait_for_selector(
                IMAGE_GEN_DESELECT, timeout=timeout, state="visible"
            )
        else:
            deselect = await page.query_selector(IMAGE_GEN_DESELECT)

        if deselect:
            label = await deselect.get_attribute("aria-label")
            if label and ("图片" in label or "image" in label.lower()):
                return True
        return False
    except Exception:
        return False


async def activate_image_generation(page: Page) -> bool:
    """激活图片生成功能"""
    print("激活图片生成功能...")
    try:
        if await is_image_generation_activated(page, wait=False):
            print("图片生成已激活")
            return True

        # 点击 Tools 菜单
        tools_btn = None
        for selector in TOOLS_BUTTON:
            try:
                tools_btn = await page.wait_for_selector(selector, state="visible", timeout=5000)
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
                option = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if option:
                    await option.evaluate("el => el.click()")
                    return True
            except Exception:
                continue

        return False
    except Exception as e:
        print(f"激活图片生成失败: {e}")
        return False


async def prepare_environment(
    page: Page, model: Literal["Pro", "Fast"] = "Fast", temporary_chat: bool = False
) -> bool:
    """准备页面环境（新对话 + 激活图片生成 + 选择模型）"""
    _ = temporary_chat
    try:
        if not await start_new_chat(page):
            print("开启新对话失败")

        await activate_image_generation(page)
        await ensure_model_selection(page, model)

        if not await activate_image_generation(page):
            print("激活图片生成失败")
            return False

        print("页面环境准备完成")
        return True
    except Exception as e:
        print(f"页面环境准备失败: {e}")
        return False


# =========================================================================
# 输入动作
# =========================================================================


async def upload_image_by_paste(page: Page, image_path: str) -> bool:
    """通过粘贴方式上传图片"""
    print(f"上传图片（粘贴）: {image_path}")
    image_file = Path(image_path)
    if not image_file.exists():
        print(f"图片不存在: {image_path}")
        return False

    try:
        input_box = await page.wait_for_selector(INPUT_BOX, state="visible", timeout=10000)
        if not input_box:
            return False

        await input_box.click()

        with open(image_file, "rb") as f:
            image_data = f.read()

        image_base64 = base64.b64encode(image_data).decode()

        suffix = image_file.suffix.lower()
        mime_type = {
            "jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }.get(suffix, "image/webp")
        file_ext = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png"}.get(suffix, ".webp")

        result = await page.evaluate(
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
        return result.get("success", False)
    except Exception as e:
        print(f"粘贴上传失败: {e}")
        return False


async def upload_images_by_paste(page: Page, image_paths: List[str]) -> bool:
    """批量上传图片"""
    for i, path in enumerate(image_paths):
        if not await upload_image_by_paste(page, path):
            return False
        await page.wait_for_timeout(500)
    return True


async def get_uploaded_image_count(page: Page) -> int:
    """获取已上传到输入框的图片数量"""
    try:
        count = await page.evaluate(
            f"""
            () => {{
                const input = document.querySelector('{INPUT_BOX}');
                if (!input) return 0;
                return input.querySelectorAll('img').length;
            }}
        """
        )
        return int(count)
    except Exception:
        return 0


async def input_prompt(page: Page, prompt: str) -> bool:
    """输入指令"""
    print(f"输入: {prompt}")
    try:
        input_box = await page.wait_for_selector(INPUT_BOX, state="visible", timeout=10000)
        if input_box:
            await input_box.fill(prompt)
            return True
        return False
    except Exception as e:
        print(f"输入失败: {e}")
        return False


async def submit(page: Page) -> bool:
    """提交生成请求"""
    print("提交请求...")
    try:
        for selector in SUBMIT_BUTTON:
            try:
                btn = await page.wait_for_selector(selector, state="visible", timeout=3000)
                if btn:
                    await btn.click()
                    return True
            except Exception:
                continue
        return False
    except Exception as e:
        print(f"提交失败: {e}")
        return False


async def dismiss_consent_dialog(page: Page) -> bool:
    """关闭同意弹窗"""
    try:
        for selector in AGREE_BUTTON:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await btn.click()
                return True
        return False
    except Exception:
        return False


# =========================================================================
# 结果获取动作
# =========================================================================


async def wait_for_generation(page: Page, timeout: int = 60) -> bool:
    """等待图片生成完成"""
    print(f"等待生成（最多 {timeout} 秒）...")
    try:
        await page.wait_for_function(
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


async def get_generated_image_count(page: Page) -> int:
    """获取生成的图片数量"""
    for selector in RESPONSE_CONTAINER:
        try:
            containers = await page.query_selector_all(selector)
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


async def get_generated_image_urls(page: Page) -> List[str]:
    """获取所有生成图片的 URL"""
    urls = []
    for selector in RESPONSE_CONTAINER:
        try:
            containers = await page.query_selector_all(selector)
            if containers:
                container = containers[-1]
                images = await container.query_selector_all("img")
                for img in images:
                    src = await img.get_attribute("src")
                    if is_generated_image(src):
                        urls.append(src)
                if urls:
                    return urls
        except Exception:
            continue
    return urls


# =========================================================================
# 下载动作
# =========================================================================


async def download_via_hover(page: Page, img_element) -> Optional[bytes]:
    """通过 hover 触发下载按钮获取原图"""
    try:
        await page.evaluate(
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
                download_btn = await page.wait_for_selector(selector, state="visible", timeout=1000)
                if download_btn:
                    break
            except Exception:
                continue

        if not download_btn:
            return None

        for attempt in range(5):
            try:
                async with page.expect_download(timeout=5000) as download_info:
                    await download_btn.click(no_wait_after=True)
                download = await download_info.value
                download_path = await download.path()
                if download_path:
                    with open(download_path, "rb") as f:
                        return f.read()
            except Exception:
                await asyncio.sleep(0.5)
                continue

        return None
    except Exception:
        return None


async def download_image_by_index(
    page: Page,
    index: int,
    save_path: str,
    output_format: str = "webp",
    lossless: bool = True,
    quality: int = 80,
    remove_watermark: bool = True,
    skip_hd: bool = False,
) -> tuple[bool, Optional[str]]:
    """按索引下载生成的图片"""
    # 找到目标图片
    target_img = None
    for selector in RESPONSE_CONTAINER:
        try:
            containers = await page.query_selector_all(selector)
            if containers:
                container = containers[-1]
                images = await container.query_selector_all("img")
                generated = [
                    img for img in images if is_generated_image(await img.get_attribute("src"))
                ]
                if index < len(generated):
                    target_img = generated[index]
                    break
        except Exception:
            continue

    if not target_img:
        return False, None

    image_bytes = None
    if not skip_hd:
        image_bytes = await download_via_hover(page, target_img)

    if not image_bytes:
        url = await target_img.get_attribute("src")
        response = await page.request.get(url)
        if response.ok:
            image_bytes = await response.body()
        else:
            return False, None

    return await save_image_bytes(
        image_bytes, save_path, output_format, lossless, quality, remove_watermark
    )


async def save_image_bytes(
    image_bytes: bytes,
    save_path: str,
    output_format: str = "webp",
    lossless: bool = True,
    quality: int = 80,
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
            if lossless:
                img.save(output, "WEBP", lossless=True)
            else:
                img.save(output, "WEBP", quality=quality)
        elif output_format.lower() in ("jpg", "jpeg"):
            save_path = str(Path(save_path).with_suffix(".jpg"))
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(output, "JPEG", quality=quality)
        else:
            img.save(output, output_format.upper())

        data = output.getvalue()
        file_hash = (
            base64.urlsafe_b64encode(hashlib.sha256(data).digest())
            .decode("ascii")
            .rstrip("=")
        )

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(data)

        return True, file_hash
    except Exception as e:
        print(f"保存失败: {e}")
        return False, None


async def download_hd_by_url(
    page: Page, url: str, save_path: str, remove_watermark: bool = True
) -> tuple[bool, Optional[dict]]:
    """通过预览图 URL 下载高清图"""
    try:
        images = await page.query_selector_all("img")
        hd_bytes = None
        for img in images:
            src = await img.get_attribute("src")
            if src == url:
                hd_bytes = await download_via_hover(page, img)
                break

        if not hd_bytes:
            return False, None

        success, file_hash = await save_image_bytes(
            hd_bytes, save_path, "webp", True, 80, remove_watermark
        )
        if success:
            img = Image.open(BytesIO(hd_bytes))
            width, height = img.size
            file_size = Path(save_path).with_suffix(".webp").stat().st_size
            return True, {
                "hash": file_hash,
                "size": file_size,
                "dimensions": f"{width}x{height}",
            }
        return False, None
    except Exception:
        return False, None


# =========================================================================
# 高级任务流 (Pipelines)
# =========================================================================


async def reinitialize_page(page: Page, model: Literal["Pro", "Fast"] = "Fast") -> bool:
    """重新初始化页面"""
    try:
        await page.goto("https://gemini.google.com/app", wait_until="load", timeout=60000)
        return await prepare_environment(page, model=model)
    except Exception:
        return False


async def run_edit_pipeline(
    page: Page,
    input_image: str,
    prompt: str,
    output_dir: str,
    model: Literal["Pro", "Fast"] = "Fast",
) -> Optional[List[str]]:
    """完整的图片编辑流程管道"""
    try:
        # 1. 准备环境
        if not await prepare_environment(page, model):
            return None

        # 2. 上传图片
        if not await upload_image_by_paste(page, input_image):
            return None

        # 3. 输入指令
        if not await input_prompt(page, prompt):
            if await dismiss_consent_dialog(page):
                if not await input_prompt(page, prompt):
                    return None
            else:
                return None

        # 4. 提交并等待
        if not await submit(page):
            return None
        if not await wait_for_generation(page, timeout=120):
            return None

        # 5. 下载结果
        count = await get_generated_image_count(page)
        if count == 0:
            return None

        output_path = Path(output_dir) / datetime.now().strftime("%Y%m%d")
        output_path.mkdir(parents=True, exist_ok=True)

        result_paths = []
        for i in range(count):
            temp_path = output_path / f"temp_{i}.webp"
            success, file_hash = await download_image_by_index(page, i, str(temp_path))
            if success and file_hash:
                final_path = output_path / f"{file_hash}.webp"
                temp_path.rename(final_path)
                result_paths.append(str(final_path))

        # 预热下次环境
        asyncio.create_task(prepare_environment(page, model))

        return result_paths if result_paths else None

    except Exception as e:
        print(f"Pipeline failed: {e}")
        return None
