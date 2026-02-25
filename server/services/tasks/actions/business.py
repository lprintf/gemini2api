import asyncio
import base64
import hashlib
import time
import traceback
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from PIL import Image
from playwright.async_api import Page
from server.utils.logger import tab_log, DATA_DIR
from .selectors import _SELECTORS, _AVATAR_PATTERN
from .base import click, input_prompt, select_menu_item, upload_image, get_uploaded_image_count
from .environment import handle_consent_popups
from ..remove_watermark.main import WatermarkRemover

async def start_new_chat(page: Page, selector: str = _SELECTORS["input_box"]) -> bool:
    """开启新对话"""
    try:
        # 1. 优先尝试快捷键
        if "/app" in page.url:
            await page.keyboard.press("Control+Shift+O")
        
        # 2. 如果 URL 不对，强行跳转
        if "/app" not in page.url:
            await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            
        # 3. 检查输入框是否出现 (判定为成功)
        try:
            await page.wait_for_selector(selector, timeout=5000)
            return True
        except:
            # 4. 兜底：尝试点击页面上的 New Chat 按钮 (针对快捷键失效的情况)
            new_btn = await page.query_selector('a[href="/app"], .new-chat-button')
            if new_btn: 
                await new_btn.click()
                await page.wait_for_selector(selector, timeout=5000)
                return True
        return False
    except:
        return False

async def ensure_image_gen_active(page: Page) -> bool:
    """业务动作：确保图片生成功能开启"""
    
    # 1. 预检：等待一小段时间，看页面自身是否自带了“已开启”的状态
    # 包含两种情况：直接看到了取消选中按钮，或者工具按钮上有 selected 标记
    try:
        already_active_selector = (
            f"{_SELECTORS['image_gen_deselect']}, "
            ".toolbox-drawer-button.has-selected-item, "
            ".toolbox-drawer-button[class*='selected']"
        )
        # 给页面2秒钟的时间去渲染这些状态类
        is_already_active = await page.wait_for_selector(already_active_selector, timeout=2000, state="attached")
        if is_already_active:
            tab_log(page, "Image generation tool is already active (detected via UI state). Skipping click.")
            return True
    except: pass
    
    tab_log(page, "Tool state not active. Attempting to open menu...")
    # 2. 如果没能识别，我们就点开菜单检查
    try:
        all_menus = ", ".join(_SELECTORS["tools_btn"])
        menu_btn = await page.wait_for_selector(all_menus, timeout=5000, state="visible")
        if menu_btn:
            try:
                await menu_btn.click(timeout=2000)
            except:
                await menu_btn.click(timeout=3000, force=True)
                
            # 4. 等待下拉菜单中的元素渲染（可能需要等待动画）
            all_deselect = _SELECTORS["image_gen_deselect"]
            all_opt = ", ".join(_SELECTORS["image_gen_opt"])
            
            try:
                # 给足 3 秒时间等待其中任何一个出现（不论是选中状态还是未选中状态）
                target = await page.wait_for_selector(f"{all_deselect}, {all_opt}", timeout=3000, state="attached")
                
                # 现在检查具体出现的是哪一个
                is_deselected = await page.query_selector(all_deselect)
                if is_deselected:
                    tab_log(page, "Tool menu opened, found tool is already active (deselect button visible).")
                    try:
                        await menu_btn.click(timeout=2000) # 收起菜单
                    except:
                        await menu_btn.click(timeout=3000, force=True)
                    return True
                    
                opt = await page.query_selector(all_opt)
                if opt:
                    tab_log(page, "Tool menu opened, clicking tool to activate...")
                    try:
                        await opt.click(timeout=2000)
                    except:
                        await opt.click(timeout=3000, force=True)
                    return True
            except Exception as e:
                tab_log(page, f"Menu content wait failed: {e}", "warning")
    except Exception as e:
        tab_log(page, f"ensure_image_gen_active error: {e}", "error")
        
    return False

async def set_model(page: Page, model: str = "Fast"):
    """业务动作：切换模型 (内置预检优化，支持 Fast/Pro/Thinking)"""
    model_key = model.lower()
    mapping = {
        "fast": ("model_fast", ["Fast", "快速", "Flash"]),
        "flash": ("model_fast", ["Fast", "快速", "Flash"]),
        "pro": ("model_pro", ["Pro"]),
        "thinking": ("model_thinking", ["Thinking", "思考"]),
        "thought": ("model_thinking", ["Thinking", "思考"]),
    }
    
    config = mapping.get(model_key)
    if not config:
        return False 
        
    selector_key, keywords = config
    target_selectors = _SELECTORS[selector_key]
    
    try:
        all_menus = ", ".join(_SELECTORS["model_menu"])
        menu_btn = await page.wait_for_selector(all_menus, timeout=3000)
        current_text = await menu_btn.inner_text()
        
        if any(kw in current_text for kw in keywords):
            return True
    except: pass

    return await select_menu_item(page, item_selectors=target_selectors, menu_selectors=_SELECTORS["model_menu"])

async def upload_images_by_paste(page: Page, image_paths: List[str]):
    """批量粘贴上传图片"""
    for p in image_paths:
        await upload_image(page, p)
    return True

async def click_submit(page: Page, selectors: List[str] = _SELECTORS["submit_btns"]):
    """点击提交 (采用物理点击+JS点击双重保障，带图片上传保护)"""
    if isinstance(selectors, str): selectors = [selectors]
    
    try:
        check_selector = '.image-preview, .image-preview.loading, .progress-spinner, mat-progress-bar'
        if await page.query_selector(check_selector):
            tab_log(page, "Detected image elements, ensuring upload completion...")
            await page.wait_for_function("""
                () => {
                    const loaders = document.querySelector('.image-preview.loading, .progress-spinner, mat-progress-bar');
                    return !loaders;
                }
            """, timeout=30000)
    except Exception as e:
        tab_log(page, f"click_submit sync wait finished or failed: {e}", "warning")

    return await click(page, selectors)

async def submit_image_prompt(page: Page, prompt: str, image_paths: List[str] = []) -> bool:
    """复合动作：上传多图 + 填词 + 提交 (内置数量校验与终极同步)"""
    try:
        target_count = len(image_paths)
        if image_paths:
            tab_log(page, f"Starting batch upload for {target_count} images...")
            for p in image_paths:
                await upload_image(page, p)
        
        if prompt:
            await input_prompt(page, prompt)
            
        if target_count > 0:
            tab_log(page, f"Waiting for image count to reach {target_count}...")
            try:
                await page.wait_for_function(f"""
                    (count) => document.querySelectorAll('img[src*="blob:"]').length >= count
                """, arg=target_count, timeout=90000)
            except:
                tab_log(page, f"Warning: Image count sync timeout (curr={await get_uploaded_image_count(page)}, expected={target_count})", "warning")

        return await click_submit(page)
    except Exception as e:
        tab_log(page, f"submit_image_prompt error: {e}", "error")
        return False

async def wait_for_results(page: Page, timeout_s: int = 60):
    """等待结果生成完成"""
    try:
        await page.wait_for_function(f"""
            () => {{
                const containers = document.querySelectorAll('model-response, response-container');
                if (containers.length === 0) return false;
                const last = containers[containers.length - 1];
                const imgs = Array.from(last.querySelectorAll('img'));
                return imgs.some(i => i.src.includes('googleusercontent') && !i.src.includes('{_AVATAR_PATTERN}'));
            }}
        """, timeout=timeout_s * 1000)
        return True
    except:
        return False

async def get_generated_urls(page: Page) -> List[str]:
    """获取生成的图片 URL 列表 (锁定最后一个回复容器)"""
    return await page.evaluate(f"""
        () => {{
            const containers = document.querySelectorAll('model-response, response-container, .model-response');
            if (containers.length === 0) return [];
            const last = containers[containers.length - 1];
            const urls = Array.from(last.querySelectorAll('img'))
                .map(i => i.src)
                .filter(src => src && src.includes('googleusercontent') && !src.includes('{_AVATAR_PATTERN}'));
            return [...new Set(urls)];
        }}
    """)

async def download_hd_image(page: Page, img_url: str, remove_wm: bool = True, max_attempts: int = 9):
    """下载高清图片 (精准 Hover 下载版，纯内存处理)"""
    img_element = None
    try:
        img_element = await page.evaluate_handle("""
            (url) => {
                const containers = document.querySelectorAll('model-response, response-container, .model-response');
                if (containers.length === 0) return null;
                const last = containers[containers.length - 1];
                return Array.from(last.querySelectorAll('img')).find(i => i.src === url);
            }
        """, img_url)
        img_element = img_element.as_element()
    except: pass
    
    if img_element:
        for attempt in range(max_attempts):
            is_last = (attempt == max_attempts - 1)
            try:
                tab_log(page, f"Hovering over image (attempt {attempt + 1}/{max_attempts})...")
                await img_element.scroll_into_view_if_needed()
                try:
                    await img_element.hover(timeout=3000)
                except:
                    await img_element.dispatch_event("mouseenter")
                
                download_btn = None
                selectors = [
                    'button[aria-label*="Download"]',
                    'button[aria-label*="下载"]',
                    '.download-button',
                    'button:has(mat-icon:has-text("download"))'
                ]
                for sel in selectors:
                    try:
                        download_btn = await page.wait_for_selector(sel, timeout=2000, state="visible")
                        if download_btn:
                            tab_log(page, f"Download button found: {sel}")
                            break
                    except: continue
                if download_btn:
                    t_dl_start = time.time()
                    async with page.expect_download(timeout=60000) as download_info:
                        await download_btn.click()
                    download = await download_info.value
                    path = await download.path()
                    dl_time = round(time.time() - t_dl_start, 3)
                    if path:
                        buf = BytesIO(Path(path).read_bytes())
                        success, img_bytes, img_hash, p_stats = await _process_image(buf, remove_wm)
                        if success:
                            p_stats["dl_time"] = dl_time
                            p_stats["mode"] = "hd"
                        return success, img_bytes, img_hash, p_stats
                if not is_last: continue
            except Exception as e:
                if is_last:
                    tab_log(page, f"HD download failed after {max_attempts} attempts: {e}", "error")
                else: 
                    tab_log(page, f"Hover attempt {attempt+1} failed ({type(e).__name__}), retrying...", "warning")
        
    tab_log(page, "Falling back to direct request.", "warning")
    success, img_bytes, h, stats = await download_q_image(page, img_url, remove_wm)
    if stats:
        stats["mode"] = "hd_fallback_q"
    return success, img_bytes, h, stats

async def download_q_image(page: Page, img_url: str, remove_wm: bool = True):
    """通过 URL 直接请求下载预览图 (纯内存处理)"""
    stats = {}
    try:
        t_dl_start = time.time()
        response = await page.request.get(img_url)
        dl_time = round(time.time() - t_dl_start, 3)
        if response.ok:
            success, img_bytes, h, p_stats = await _process_image(BytesIO(await response.body()), remove_wm)
            if success:
                stats.update(p_stats)
                stats["dl_time"] = dl_time
                stats["mode"] = "preview"
            return success, img_bytes, h, stats
    except Exception as e:
        tab_log(page, f"download_q_image failed: {e}", "error")
    return False, None, None, stats

async def download_generated_images(page: Page, remove_watermark: bool = True, download_mode: str = "preview") -> List[Dict[str, Any]]:
    """获取所有生成的图片 URL 并下载处理（纯内存，直接用 hash 文件名落盘）"""
    urls = await get_generated_urls(page)
    if not urls: return []
    images_info = []
    output_base = Path("data/outputs")
    date_str = datetime.now().strftime("%Y%m%d")
    for i, url in enumerate(urls):
        if download_mode == "hd":
            success, img_bytes, img_hash, stats = await download_hd_image(page, url, remove_wm=remove_watermark)
        else:
            success, img_bytes, img_hash, stats = await download_q_image(page, url, remove_wm=remove_watermark)
        if success and img_hash and img_bytes:
            save_dir = output_base / ("hd" if download_mode == "hd" else "q") / date_str
            save_dir.mkdir(parents=True, exist_ok=True)
            final_path = save_dir / f"{img_hash}.webp"
            final_path.write_bytes(img_bytes)
            raw_size = stats.get('raw_size_kb', 0)
            final_size = stats.get('size_kb', 0)
            ratio = round((final_size / raw_size * 100), 1) if raw_size > 0 else 0
            tab_log(page, f"Download Meta: {img_hash} ({stats.get('mode', 'unknown')}) | Size: {raw_size}KB -> {final_size}KB ({ratio}%) | DL: {stats.get('dl_time', 0)}s | WM_Remove: {stats.get('wm_time', 0)}s | Encode: {stats.get('save_time', 0)}s")
            images_info.append({"id": f"{date_str}/{img_hash}", "hash": img_hash, "date": date_str, "format": "webp", "url": url})
    return images_info

async def _process_image(src: BytesIO, remove_wm: bool):
    """图片纯内存处理：去水印 + WebP 编码，返回 (success, img_bytes, hash, stats)"""
    stats = {}
    try:
        t_start = time.time()
        raw_size = src.getbuffer().nbytes
        stats["raw_size_kb"] = round(raw_size / 1024, 2)
        img = Image.open(src)
        img.load()
        if remove_wm:
            t_wm = time.time()
            img = await asyncio.to_thread(WatermarkRemover.remove_watermark, img)
            stats["wm_time"] = round(time.time() - t_wm, 3)
        t_enc = time.time()
        out_buf = BytesIO()
        await asyncio.to_thread(img.save, out_buf, "WEBP", lossless=True)
        img_bytes = out_buf.getvalue()
        stats["save_time"] = round(time.time() - t_enc, 3)
        stats["size_kb"] = round(len(img_bytes) / 1024, 2)
        h = base64.urlsafe_b64encode(hashlib.sha256(img_bytes).digest()).decode().rstrip("=")
        stats["process_total"] = round(time.time() - t_start, 3)
        return True, img_bytes, h, stats
    except Exception as e:
        traceback.print_exc()
        return False, None, None, stats
