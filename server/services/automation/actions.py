"""
Gemini 原子动作 - 纯函数化的浏览器自动化操作 (已解耦选择器)
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

from .watermark import WatermarkRemover

# =========================================================================
# 辅助工具 (以前在 selectors.py 中)
# =========================================================================

def is_generated_image(src: str, avatar_pattern: str = "/a/ACg8oc") -> bool:
    """判断是否为生成的图片（排除头像）"""
    return src and "googleusercontent" in src and avatar_pattern not in src

def get_model_keywords(model: str) -> List[str]:
    """获取模型关键词用于验证"""
    if model == "Fast":
        return ["Fast", "快速", "flash"]
    else:
        return ["Pro", "pro"]

# =========================================================================
# 环境准备动作
# =========================================================================

async def start_new_chat(page: Page, input_box_selector: str = 'div[contenteditable="true"]') -> bool:
    """开启新对话（Ctrl+Shift+O）"""
    print("开启新对话...")
    try:
        current_url = page.url
        is_new_chat = bool(re.match(r"^https://[^/]+/app(?:[?#].*)?$", current_url))

        if is_new_chat:
            input_box = await page.query_selector(input_box_selector)
            if input_box:
                print("已在新对话页面，跳过刷新")
                return True

        await page.keyboard.press("Control+Shift+O")
        try:
            await page.wait_for_selector(input_box_selector, timeout=5000)
        except:
            pass

        if "/app" in page.url:
            print(f"新对话已开启: {page.url}")
            return True

        await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
        await page.wait_for_selector(input_box_selector, timeout=5000)
        return True

    except Exception as e:
        print(f"开启新对话失败: {e}")
        return False

async def ensure_model_selection(
    page: Page, 
    model: Literal["Pro", "Fast"] = "Fast",
    menu_selector: str = '[data-test-id="bard-mode-menu-button"]',
    fast_selectors: List[str] = None,
    pro_selectors: List[str] = None
) -> bool:
    """确保选择了指定的模型"""
    print(f"选择模型: {model}")
    try:
        await page.wait_for_selector(menu_selector, timeout=5000, state="attached")
        menu_button = page.locator(menu_selector)
        button_text = await menu_button.inner_text()

        fast_keywords = get_model_keywords("Fast")
        pro_keywords = get_model_keywords("Pro")

        is_fast = any(kw in button_text or kw.lower() in button_text.lower() for kw in fast_keywords)
        is_pro = any(kw in button_text or kw.lower() in button_text.lower() for kw in pro_keywords)

        if (model == "Fast" and is_fast) or (model == "Pro" and is_pro):
            print(f"已是 {model} 模型")
            return True

        target_selectors = fast_selectors if model == "Fast" else pro_selectors
        if not target_selectors:
            return False

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

async def activate_image_generation(
    page: Page,
    tools_selectors: List[str],
    option_selectors: List[str],
    deselect_selector: str
) -> bool:
    """激活图片生成功能"""
    print("激活图片生成功能...")
    try:
        # 检查是否已激活
        deselect = await page.query_selector(deselect_selector)
        if deselect:
            label = await deselect.get_attribute("aria-label")
            if label and ("图片" in label or "image" in label.lower()):
                print("图片生成已激活")
                return True

        # 点击 Tools 菜单
        tools_btn = None
        for selector in tools_selectors:
            try:
                tools_btn = await page.wait_for_selector(selector, state="visible", timeout=5000)
                if tools_btn: break
            except: continue

        if not tools_btn: return False
        await tools_btn.click(no_wait_after=True)

        # 点击图片生成选项
        for selector in option_selectors:
            try:
                option = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if option:
                    await option.evaluate("el => el.click()")
                    return True
            except: continue

        return False
    except Exception as e:
        print(f"激活图片生成失败: {e}")
        return False

async def upload_image_by_paste(page: Page, image_path: str, input_box_selector: str) -> bool:
    """通过粘贴方式上传图片"""
    image_file = Path(image_path)
    if not image_file.exists(): return False

    try:
        input_box = await page.wait_for_selector(input_box_selector, state="visible", timeout=10000)
        if not input_box: return False
        await input_box.click()

        with open(image_file, "rb") as f:
            image_data = f.read()
        image_base64 = base64.b64encode(image_data).decode()

        suffix = image_file.suffix.lower()
        mime_type = {"jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(suffix, "image/webp")
        file_ext = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png"}.get(suffix, ".webp")

        result = await page.evaluate("""
            async (args) => {
                const [imageBase64, mimeType, fileExt, selector] = args;
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
                    const target = document.querySelector(selector);
                    if (!target) return { success: false };
                    const pasteEvent = new ClipboardEvent('paste', {
                        bubbles: true, cancelable: true, clipboardData: dataTransfer
                    });
                    target.focus();
                    target.dispatchEvent(pasteEvent);
                    return { success: true };
                } catch (e) { return { success: false }; }
            }
        """, [image_base64, mime_type, file_ext, input_box_selector])
        return result.get("success", False)
    except Exception as e:
        print(f"粘贴上传失败: {e}")
        return False

async def submit(page: Page, submit_selectors: List[str]) -> bool:
    """提交生成请求"""
    print("提交请求...")
    for selector in submit_selectors:
        try:
            btn = await page.wait_for_selector(selector, state="visible", timeout=3000)
            if btn:
                await btn.click()
                return True
        except: continue
    return False

async def wait_for_generation(page: Page, timeout: int = 60) -> bool:
    """等待图片生成完成 (逻辑通用)"""
    print(f"等待生成（最多 {timeout} 秒）...")
    try:
        await page.wait_for_function("""
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
            """, timeout=timeout * 1000)
        return True
    except: return False

async def get_generated_image_urls(page: Page, container_selectors: List[str]) -> List[str]:
    """获取所有生成图片的 URL"""
    urls = []
    for selector in container_selectors:
        try:
            containers = await page.query_selector_all(selector)
            if containers:
                container = containers[-1]
                images = await container.query_selector_all("img")
                for img in images:
                    src = await img.get_attribute("src")
                    if is_generated_image(src):
                        urls.append(src)
                if urls: return urls
        except: continue
    return urls

async def download_via_hover(page: Page, img_element, download_selectors: List[str]) -> Optional[bytes]:
    """通过 hover 触发下载按钮获取原图"""
    try:
        await page.evaluate("(img) => { img.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); }", img_element)
        download_btn = None
        for selector in download_selectors:
            try:
                download_btn = await page.wait_for_selector(selector, state="visible", timeout=1000)
                if download_btn: break
            except: continue

        if not download_btn: return None
        async with page.expect_download(timeout=5000) as download_info:
            await download_btn.click(no_wait_after=True)
        download = await download_info.value
        path = await download.path()
        if path:
            with open(path, "rb") as f: return f.read()
        return None
    except: return None

async def download_image_by_index(
    page: Page,
    index: int,
    save_path: str,
    container_selectors: List[str],
    download_selectors: List[str],
    remove_watermark: bool = True,
    skip_hd: bool = False
) -> tuple[bool, Optional[str]]:
    """按索引下载生成的图片"""
    target_img = None
    for selector in container_selectors:
        try:
            containers = await page.query_selector_all(selector)
            if containers:
                container = containers[-1]
                images = await container.query_selector_all("img")
                generated = [img for img in images if is_generated_image(await img.get_attribute("src"))]
                if index < len(generated):
                    target_img = generated[index]
                    break
        except: continue

    if not target_img: return False, None

    image_bytes = None
    if not skip_hd:
        image_bytes = await download_via_hover(page, target_img, download_selectors)

    if not image_bytes:
        url = await target_img.get_attribute("src")
        response = await page.request.get(url)
        if response.ok: image_bytes = await response.body()
        else: return False, None

    return await save_image_bytes(image_bytes, save_path, remove_watermark)

async def save_image_bytes(image_bytes: bytes, save_path: str, remove_watermark: bool = True) -> tuple[bool, Optional[str]]:
    """保存图片"""
    try:
        img = Image.open(BytesIO(image_bytes))
        if remove_watermark:
            img = WatermarkRemover.remove_watermark(img)
        
        output = BytesIO()
        img.save(output, "WEBP", lossless=True)
        data = output.getvalue()
        file_hash = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
        
        final_path = Path(save_path).with_suffix(".webp")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with open(final_path, "wb") as f: f.write(data)
        return True, file_hash
    except Exception as e:
        print(f"保存失败: {e}")
        return False, None

async def download_hd_by_url(page: Page, url: str, save_path: str, download_selectors: List[str], remove_watermark: bool = True) -> tuple[bool, Optional[dict]]:
    """通过预览图 URL 下载高清图"""
    try:
        images = await page.query_selector_all("img")
        hd_bytes = None
        for img in images:
            if await img.get_attribute("src") == url:
                hd_bytes = await download_via_hover(page, img, download_selectors)
                break
        if not hd_bytes: return False, None

        success, file_hash = await save_image_bytes(hd_bytes, save_path, remove_watermark)
        if success:
            img = Image.open(BytesIO(hd_bytes))
            width, height = img.size
            file_size = Path(save_path).with_suffix(".webp").stat().st_size
            return True, {"hash": file_hash, "size": file_size, "dimensions": f"{width}x{height}"}
        return False, None
    except: return False, None

# --- 业务流 ---

async def prepare_environment(page: Page, task: Any, model: str = "Fast") -> bool:
    """准备页面环境"""
    if not await start_new_chat(page, task.INPUT_BOX): return False
    
    # 激活图片生成 (只有 ImageGenerationTask 有这些选择器，如果是 ReinitializeTask 则默认可能已激活或跳过)
    if hasattr(task, "TOOLS_BUTTON"):
        await activate_image_generation(page, task.TOOLS_BUTTON, task.IMAGE_GEN_OPTION, task.IMAGE_GEN_DESELECT)
    
    # 选择模型
    if hasattr(task, "MODEL_MENU_BUTTON"):
        await ensure_model_selection(page, model, task.MODEL_MENU_BUTTON, task.MODEL_OPTION_FAST, task.MODEL_OPTION_PRO)
    
    return True

async def reinitialize_page(page: Page, task: Any, model: str = "Fast") -> bool:
    """重新初始化页面"""
    try:
        await page.goto("https://gemini.google.com/app", wait_until="load", timeout=60000)
        # 处理同意弹窗
        for selector in getattr(task, "AGREE_BUTTON", []):
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible(): await btn.click()
            except: pass
        return await prepare_environment(page, task, model=model)
    except: return False
