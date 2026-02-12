"""
Gemini 原子动作 - 封装了所有物理选择器和原始交互
"""

import asyncio
import base64
import hashlib
import re
import time
import traceback
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from PIL import Image
from playwright.async_api import Page

from .remove_watermark.main import WatermarkRemover
from server.utils.logger import tab_log, DATA_DIR

# =========================================================================
# 物理层定位符 (内部隐藏)
# =========================================================================

_SELECTORS = {
    "input_box": 'div[contenteditable="true"]',
    "submit_btns": [
        'button[aria-label*="发送"]',
        'button[aria-label*="Send"]',
        'button[aria-label*="submit"]',
        'button[data-test-id="send-button"]',
    ],
    "model_menu": [
        '[data-test-id="bard-mode-menu-button"]',
        'button[aria-label*="Model"]',
        'button[aria-label*="模型"]',
    ],
    "model_fast": [
        '[data-test-id="bard-mode-option-fast"]',
        '[data-test-id="bard-mode-option-快速"]',
        '[data-test-id="bard-mode-option-Flash"]',
    ],
    "model_thinking": [ # 目前不如pro好用，指令跟随能力差
        '[data-test-id="bard-mode-option-thinking"]',
        '[data-test-id="bard-mode-option-思考"]',
        '[data-test-id="bard-mode-option-Thinking"]',
    ],
    "model_pro": [
        '[data-test-id="bard-mode-option-pro"]',
        '[data-test-id="bard-mode-option-Pro"]',
    ],
    "tools_btn": [
        "button.toolbox-drawer-button",
        'button[aria-label="工具"]',
        'button[aria-label="Tools"]',
    ],
    "image_gen_opt": [
        'button.toolbox-drawer-item-list-button:has-text("Create images")',
        'button.toolbox-drawer-item-list-button:has-text("生成图片")',
    ],
    "image_gen_deselect": ".toolbox-drawer-item-deselect-button",
    "response_container": ["model-response", "response-container"],
    "download_btns": [
        'button[aria-label*="Download"]',
        'button[aria-label*="下载"]',
        'button[aria-label*="保存"]',
    ],
    "agree_btns": [
        'button:has-text("Agree")',
        'button:has-text("同意")',
        'button:has-text("OK")',
        '[role="dialog"] button[data-mdc-dialog-action="accept"]',
    ],
    "sign_in_btns": [
        'a[href*="accounts.google.com/ServiceLogin"]', # 最稳固的选择器
        'a:has-text("Sign in")', 
        'a:has-text("登录")',
        'button:has-text("Sign in")',
        'button:has-text("登录")',
        'button[aria-label*="Sign in"]',
        'button[aria-label*="登录"]',
    ],
}

_AVATAR_PATTERN = "/a/ACg8oc"

# =========================================================================
# 原子动作 (Verbs)
# =========================================================================

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

async def prepare_environment(page: Page, model: str = "Fast") -> bool:
    """准备页面环境：切换模型并确保功能开启"""
    await handle_consent_popups(page)
    
    # 1. 快速检查是否出现了登录按钮
    for sel in _SELECTORS["sign_in_btns"]:
        try:
            if await page.query_selector(sel):
                tab_log(page, "Login required (Sign-in button detected)", "warning")
                return False
        except: pass

    # 2. 检查是否有核心输入框
    if not await start_new_chat(page):
        tab_log(page, "Environment check failed: Input box not found", "error")
        return False
    
    # 3. 必须能成功切换模型
    if not await set_model(page, model):
        tab_log(page, f"Environment check failed: Failed to set model {model}", "error")
        return False
    
    # 4. 必须能成功开启图片生成功能 (对于图片生成任务，这是关键判定点)
    # 如果没登录或状态异常，这里通常会找不到或无法点击按钮
    if not await ensure_image_gen_active(page):
        tab_log(page, "Environment check failed: Cannot activate image generation", "error")
        return False
        
    return True



async def select_menu_item(page: Page, item_selectors: List[str], menu_selectors: List[str] = _SELECTORS["model_menu"]) -> bool:
    """原子动作：点击下拉菜单并从中选择一项 (优化版本：利用 CSS 组选择器)"""
    # 鲁棒性：支持单字符串
    if isinstance(item_selectors, str): item_selectors = [item_selectors]
    if isinstance(menu_selectors, str): menu_selectors = [menu_selectors]
    
    try:
        # 1. 一次性等待任何一个可能的菜单按钮
        all_menus = ", ".join(menu_selectors)
        menu_btn = await page.wait_for_selector(all_menus, timeout=5000, state="visible")
        await menu_btn.click()
        
        # 2. 一次性等待任何一个可能的待选项
        all_items = ", ".join(item_selectors)
        opt = await page.wait_for_selector(all_items, timeout=3000, state="visible")
        if opt:
            try:
                await opt.click(timeout=2000)
            except:
                await opt.evaluate("el => el.click()")
            return True
    except Exception as e:
        tab_log(page, f"select_menu_item error: {e}", "error")
    return False


async def ensure_image_gen_active(page: Page) -> bool:
    """业务动作：确保图片生成功能开启"""
    if await page.query_selector(_SELECTORS["image_gen_deselect"]):
        return True
    
    # 传入列表，原子函数内部会自动遍历重试
    return await select_menu_item(page, _SELECTORS["image_gen_opt"], menu_selectors=_SELECTORS["tools_btn"])

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
        return False # 不支持的模型
        
    selector_key, keywords = config
    target_selectors = _SELECTORS[selector_key]
    
    # 状态预检：如果当前模型已对，则不点击
    try:
        # 利用 CSS 组选择器一次性获取当前活动的菜单按钮文本
        all_menus = ", ".join(_SELECTORS["model_menu"])
        menu_btn = await page.wait_for_selector(all_menus, timeout=3000)
        current_text = await menu_btn.inner_text()
        
        if any(kw in current_text for kw in keywords):
            return True
    except: pass

    return await select_menu_item(page, item_selectors=target_selectors, menu_selectors=_SELECTORS["model_menu"])

async def input_prompt(page: Page, prompt: str, selector: str = _SELECTORS["input_box"]):
    """输入提示词"""
    box = await page.wait_for_selector(selector, timeout=5000)
    await box.fill(prompt)
    return True

async def upload_image(page: Page, image_path: str, selector: str = _SELECTORS["input_box"]):
    """粘贴图片上传 (非阻塞版：仅触发粘贴)"""
    img_file = Path(image_path)
    if not img_file.exists(): return False
    
    with open(img_file, "rb") as f:
        img_data = f.read()
        img_b64 = base64.b64encode(img_data).decode()
    
    # 使用原始文件名，避免 Gemini 的"你已经上传过"重复检测
    filename = img_file.name
    
    return await page.evaluate("""
        async ([b64, target_selector, fname]) => {
            const res = await fetch(`data:image/webp;base64,${b64}`);
            const blob = await res.blob();
            const file = new File([blob], fname, { type: "image/webp" });
            const dt = new DataTransfer();
            dt.items.add(file);
            const target = document.querySelector(target_selector);
            if (!target) return false;
            target.focus();
            target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
            return true;
        }
    """, [img_b64, selector, filename])


    # 必须等待预览容器和 loading 状态出现
    # 如果这一步等不到，说明图片粘贴失败或 Gemini 没反应，后续提交肯定会缺图
    try:
        # 1. 优先等预览框出现
        await page.wait_for_selector(".image-preview", timeout=5000)
        # 2. 确认已经进入 loading 状态 (或进度条已出)
        # 这确保了 click_submit 运行时能看到“正在上传”的状态
        await page.wait_for_selector(".image-preview.loading, .progress-spinner, mat-progress-bar", timeout=6000)
        tab_log(page, "Image upload detected and loading started.")
    except:
        tab_log(page, "Warning: upload_image timed out waiting for loading state.", "warning")
    return True


async def upload_images_by_paste(page: Page, image_paths: List[str]):
    """批量粘贴上传图片"""
    for p in image_paths:
        await upload_image(page, p)
    return True

async def get_uploaded_image_count(page: Page) -> int:
    """原子动作：获取当前输入框中已物理存在的图片预览数量"""
    try:
        # 使用 blob 图片作为可靠的计数依据（确保图片实际已加载）
        count = await page.evaluate("""
            () => document.querySelectorAll('img[src*="blob:"]').length
        """)
        return int(count or 0)
    except:
        return 0

async def click(page: Page, selectors: List[str]):
    """通用点击动作 (支持多选择器回退，不含业务逻辑检查)"""
    # 鲁棒性：支持单字符串
    if isinstance(selectors, str): selectors = [selectors]
    
    for sel in selectors:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                try:
                    await btn.click(timeout=2000)
                except:
                    # JS 强制点击兜底
                    await btn.evaluate("el => el.click()")
                return True
        except: continue
    return False


async def click_submit(page: Page, selectors: List[str] = _SELECTORS["submit_btns"]):
    """点击提交 (采用物理点击+JS点击双重保障，带图片上传保护)"""
    # 鲁棒性：支持单字符串
    if isinstance(selectors, str): selectors = [selectors]
    
    # 1. 预检：如果有任何正在加载的迹象，死等它完成
    try:
        # 只要存在 preview 或任何 loading 元素，就进入等待逻辑
        # 即使现在不 loading，也要等一下确认它确实不是在 loading
        check_selector = '.image-preview, .image-preview.loading, .progress-spinner, mat-progress-bar'
        if await page.query_selector(check_selector):
            tab_log(page, "Detected image elements, ensuring upload completion...")
            await page.wait_for_function("""
                () => {
                    const loaders = document.querySelector('.image-preview.loading, .progress-spinner, mat-progress-bar');
                    return !loaders;
                }
            """, timeout=30000) # 给足够的上传时间
            # 上传完后给极短的缓冲让“发送”按钮变为可用状态
            await asyncio.sleep(0.5)
    except Exception as e:
        tab_log(page, f"click_submit sync wait finished or failed: {e}", "warning")

    # 2. 执行物理点击+JS点击双重保障
    for sel in selectors:
        try:
            btn = await page.wait_for_selector(sel, timeout=3000, state="visible")
            if btn:
                try:
                    await btn.click(timeout=2000)
                except:
                    # 针对按钮被遮挡或处于特殊状态，尝试 JS 强制点击
                    await btn.evaluate("el => el.click()")
                return True
        except: continue
    return False

async def submit_image_prompt(page: Page, prompt: str, image_paths: List[str] = []) -> bool:
    """复合动作：上传多图 + 填词 + 提交 (内置数量校验与终极同步)"""
    try:
        target_count = len(image_paths)
        
        # 1. 批量发起上传
        if image_paths:
            tab_log(page, f"Starting batch upload for {target_count} images...")
            for p in image_paths:
                await upload_image(page, p)
        
        # 2. 填写提示词
        if prompt:
            await input_prompt(page, prompt)
            
        # 3. 核心等待：直到 UI 上的图片数量达到预期
        if target_count > 0:
            tab_log(page, f"Waiting for image count to reach {target_count}...")
            try:
                await page.wait_for_function(f"""
                    (count) => document.querySelectorAll('img[src*="blob:"]').length >= count
                """, arg=target_count, timeout=90000)
            except:
                tab_log(page, f"Warning: Image count sync timeout (curr={await get_uploaded_image_count(page)}, expected={target_count})", "warning")

            
        # 4. 最终提交 (click_submit 会处理后续的 loading 消失等待)
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
            // 找到所有回复容器
            const containers = document.querySelectorAll('model-response, response-container, .model-response');
            if (containers.length === 0) return [];
            
            // 锁定最后一个
            const last = containers[containers.length - 1];
            
            // 提取容器内的图片并排重
            const urls = Array.from(last.querySelectorAll('img'))
                .map(i => i.src)
                .filter(src => src && src.includes('googleusercontent') && !src.includes('{_AVATAR_PATTERN}'));
            
            return [...new Set(urls)];
        }}
    """)

async def download_hd_image(page: Page, img_url: str, remove_wm: bool = True, max_attempts: int = 9):
    """下载高清图片 (精准 Hover 下载版，纯内存处理)"""
    # 策略：在最后一个容器中通过 JS 查找对应的 ElementHandle
    img_element = None
    try:
        # 使用 JS 辅助查找，避免 CSS 选择器转义问题
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
    
    # 1. 尝试 Hover 下载高清
    if img_element:
        # 弹性重试逻辑
        for attempt in range(max_attempts):
            is_last = (attempt == max_attempts - 1)
            try:
                tab_log(page, f"Hovering over image (attempt {attempt + 1}/{max_attempts})...")
                await img_element.scroll_into_view_if_needed()
                
                # 双重保险：物理 hover + JS 推送
                try:
                    await img_element.hover(timeout=3000)
                except:
                    # 备选：通过 JS 触发进入事件
                    await img_element.dispatch_event("mouseenter")
                
                # 稍微等按钮渲染出来
                await asyncio.sleep(0.5)

                # 等待下载按钮出现
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
                        # 读入内存后立即释放临时文件依赖
                        buf = BytesIO(Path(path).read_bytes())
                        success, img_bytes, img_hash, p_stats = await _process_image(buf, remove_wm)
                        if success:
                            p_stats["dl_time"] = dl_time
                            p_stats["mode"] = "hd"
                        return success, img_bytes, img_hash, p_stats
                
                # 如果没找到按钮且没到最后一次，继续重试
                if not is_last: continue
            except Exception as e:
                if is_last:
                    tab_log(page, f"HD download failed after {max_attempts} attempts: {e}", "error")
                else: 
                    tab_log(page, f"Hover attempt {attempt+1} failed ({type(e).__name__}), retrying...", "warning")
        
    tab_log(page, "Falling back to direct request.", "warning")

    # 2. 备选方案：如果 Hover 失败或找不到按钮，通过 URL 直接下载
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

async def download_generated_images(
    page: Page, 
    remove_watermark: bool = True,
    download_mode: str = "preview"
) -> List[Dict[str, Any]]:
    """获取所有生成的图片 URL 并下载处理（纯内存，直接用 hash 文件名落盘）"""
    urls = await get_generated_urls(page)
    if not urls:
        return []

    images_info = []
    output_base = Path("data/outputs")
    date_str = datetime.now().strftime("%Y%m%d")
    
    for i, url in enumerate(urls):
        if download_mode == "hd":
            success, img_bytes, img_hash, stats = await download_hd_image(
                page, url, remove_wm=remove_watermark
            )
        else:
            success, img_bytes, img_hash, stats = await download_q_image(
                page, url, remove_wm=remove_watermark
            )
        
        if success and img_hash and img_bytes:
            save_dir = output_base / ("hd" if download_mode == "hd" else "q") / date_str
            save_dir.mkdir(parents=True, exist_ok=True)
            final_path = save_dir / f"{img_hash}.webp"
            final_path.write_bytes(img_bytes)
            
            # 打印详细统计
            raw_size = stats.get('raw_size_kb', 0)
            final_size = stats.get('size_kb', 0)
            ratio = round((final_size / raw_size * 100), 1) if raw_size > 0 else 0
            
            tab_log(page, f"Download Meta: {img_hash} ({stats.get('mode', 'unknown')}) | "
                  f"Size: {raw_size}KB -> {final_size}KB ({ratio}%) | "
                  f"DL: {stats.get('dl_time', 0)}s | "
                  f"WM_Remove: {stats.get('wm_time', 0)}s | "
                  f"Encode: {stats.get('save_time', 0)}s")

            images_info.append({
                "id": f"{date_str}/{img_hash}",
                "hash": img_hash,
                "date": date_str,
                "format": "webp",
                "url": url,
            })
            
    return images_info

async def _process_image(src: BytesIO, remove_wm: bool):
    """图片纯内存处理：去水印 + WebP 编码，返回 (success, img_bytes, hash, stats)"""
    stats = {}
    try:
        t_start = time.time()
        
        # 获取原始大小
        raw_size = src.getbuffer().nbytes
        stats["raw_size_kb"] = round(raw_size / 1024, 2)

        img = Image.open(src)
        img.load()
        
        if remove_wm:
            t_wm = time.time()
            img = await asyncio.to_thread(WatermarkRemover.remove_watermark, img)
            stats["wm_time"] = round(time.time() - t_wm, 3)
        
        # WebP 编码到内存
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

async def handle_consent_popups(page: Page, selectors: List[str] = _SELECTORS["agree_btns"]) -> bool:
    """处理各种同意弹窗"""
    # 鲁棒性：支持单字符串
    if isinstance(selectors, str): selectors = [selectors]
    
    found = False

    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                found = True
        except: pass
    return found

async def reinitialize_page(page: Page, model: str = "Fast") -> bool:
    """初始化/重置页面环境"""
    try:
        await page.goto("https://gemini.google.com/app", wait_until="load", timeout=60000)
        return await prepare_environment(page, model)
    except:
        return False

# =========================================================================
# Debug & Analysis Actions
# =========================================================================

async def dump_inspect(page: Page) -> bool:
    """[Debug] 分析并输出当前页面的交互元素清单"""
    script = """
    () => {
        const results = [];
        const elements = document.querySelectorAll('button, a, input, [role="button"], [contenteditable="true"]');
        elements.forEach(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== 'hidden') {
                results.push({
                    tag: el.tagName,
                    text: (el.innerText || el.value || "").trim().substring(0, 50).replace(/\\n/g, ' '),
                    label: el.getAttribute('aria-label') || "",
                    selector: el.id ? `#${el.id}` : (el.className ? `.${el.className.split(' ').join('.')}` : '')
                });
            }
        });
        return results;
    }
    """
    try:
        elements = await page.evaluate(script)
        tab_log(page, f"--- Page Inspection ({len(elements)} elements) ---")
        for idx, el in enumerate(elements):
            msg = f"[{idx}] <{el['tag']}> Text: '{el['text']}'"
            if el['label']: msg += f" | Label: '{el['label']}'"
            if el['selector']: msg += f" | Sel: {el['selector']}"
            tab_log(page, msg)
        tab_log(page, "--- End of Inspection ---")
        return True
    except Exception as e:
        tab_log(page, f"Inspection failed: {e}", "error")
        return False

async def dump_html(page: Page) -> bool:
    """[Debug] 保存当前页面源码到 data/debug 目录"""
    try:
        html = await page.content()
        date_str = datetime.now().strftime("%Y%m%d")
        time_str = datetime.now().strftime("%H%M%S")
        
        debug_dir = DATA_DIR / "debug" / date_str
        debug_dir.mkdir(parents=True, exist_ok=True)
        file_path = debug_dir / f"{time_str}.html"
        file_path.write_text(html, encoding="utf-8")
        
        tab_log(page, f"HTML Source saved: {file_path}")
        return True
    except Exception as e:
        tab_log(page, f"Failed to save HTML: {e}", "error")
        return False

async def listen(page: Page, duration: Any = 30.0) -> bool:
    """[Debug] 开启当前页面监听（录像机模式）。记录 DOM 变动到日志。"""
    try:
        duration_val = float(duration)
    except:
        duration_val = 30.0

    def handle_console(msg):
        if msg.text.startswith("[DOM] "):
            tab_log(page, f"[Monitor] {msg.text[6:]}")

    setup_script = """
    (() => {
        if (window._dom_observer) return;
        const log = (m) => console.log("[DOM] " + m);
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((m) => {
                if (m.type === 'childList') {
                    m.addedNodes.forEach(node => {
                        if (node.nodeType === 1) {
                            const desc = `<${node.tagName}> ${node.className || ""}`.substring(0, 60);
                            const text = (node.innerText || node.textContent || "").trim().substring(0, 30);
                            if (text) log(`ADD: ${desc} | "${text}"`);
                        }
                    });
                } else if (m.type === 'characterData') {
                    const text = m.target.data.trim();
                    if (text.length > 2) log(`TEXT: "${text.substring(0, 50)}"`);
                }
            });
        });
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
        window._dom_observer = observer;
        console.log("[DOM] --- Listener Injected ---");
    })();
    """

    async def run_monitor():
        tab_log(page, f"--- Monitoring Current Page for {duration_val}s ---")
        page.on("console", handle_console)
        try:
            await page.evaluate(setup_script)
        except: pass
        await asyncio.sleep(duration_val)
        page.remove_listener("console", handle_console)
        await page.evaluate("() => { if(window._dom_observer) window._dom_observer.disconnect(); delete window._dom_observer; }")
        tab_log(page, f"--- Monitoring Finished ---")

    asyncio.create_task(run_monitor())
    return True


