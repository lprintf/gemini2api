"""
Gemini 原子动作 - 封装了所有物理选择器和原始交互
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

from .remove_watermark.main import WatermarkRemover

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
    # "model_thinking": [
    "model_pro": [
        '[data-test-id="bard-mode-option-thinking"]',
        '[data-test-id="bard-mode-option-思考"]',
        '[data-test-id="bard-mode-option-Thinking"]',
    ],
    # "model_pro": [
    #     '[data-test-id="bard-mode-option-pro"]',
    #     '[data-test-id="bard-mode-option-Pro"]',
    # ],
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
    await start_new_chat(page)
    
    # 切换模型
    await set_model(page, model)
    
    # 激活图片生成 (如果需要)
    await ensure_image_gen_active(page)
    return True

async def select_menu_item(page: Page, item_selectors: List[str], menu_selectors: List[str] = _SELECTORS["model_menu"]) -> bool:
    """原子动作：点击下拉菜单并从中选择一项 (优化版本：利用 CSS 组选择器)"""
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
        print(f"[Action] select_menu_item error: {e}")
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
        img_b64 = base64.b64encode(f.read()).decode()
    
    return await page.evaluate("""
        async ([b64, target_selector]) => {
            const res = await fetch(`data:image/webp;base64,${b64}`);
            const blob = await res.blob();
            const file = new File([blob], "input.webp", { type: "image/webp" });
            const dt = new DataTransfer();
            dt.items.add(file);
            const target = document.querySelector(target_selector);
            if (!target) return false;
            target.focus();
            target.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
            return true;
        }
    """, [img_b64, selector])

    # 必须等待预览容器和 loading 状态出现
    # 如果这一步等不到，说明图片粘贴失败或 Gemini 没反应，后续提交肯定会缺图
    try:
        # 1. 优先等预览框出现
        await page.wait_for_selector(".image-preview", timeout=5000)
        # 2. 确认已经进入 loading 状态 (或进度条已出)
        # 这确保了 click_submit 运行时能看到“正在上传”的状态
        await page.wait_for_selector(".image-preview.loading, .progress-spinner, mat-progress-bar", timeout=6000)
        print("[Action] Image upload detected and loading started.")
    except:
        print("[Action] Warning: upload_image timed out waiting for loading state. Image might be missing.")
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
    # 1. 预检：如果有任何正在加载的迹象，死等它完成
    try:
        # 只要存在 preview 或任何 loading 元素，就进入等待逻辑
        # 即使现在不 loading，也要等一下确认它确实不是在 loading
        check_selector = '.image-preview, .image-preview.loading, .progress-spinner, mat-progress-bar'
        if await page.query_selector(check_selector):
            print("[Action] Detected image elements, ensuring upload completion...")
            await page.wait_for_function("""
                () => {
                    const loaders = document.querySelector('.image-preview.loading, .progress-spinner, mat-progress-bar');
                    return !loaders;
                }
            """, timeout=30000) # 给足够的上传时间
            # 上传完后给极短的缓冲让“发送”按钮变为可用状态
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"[Action] click_submit sync wait finished or failed: {e}")

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
            print(f"[Action] Starting batch upload for {target_count} images...")
            for p in image_paths:
                await upload_image(page, p)
        
        # 2. 填写提示词
        if prompt:
            await input_prompt(page, prompt)
            
        # 3. 核心等待：直到 UI 上的图片数量达到预期
        if target_count > 0:
            print(f"[Action] Waiting for image count to reach {target_count}...")
            try:
                await page.wait_for_function(f"""
                    (count) => document.querySelectorAll('img[src*="blob:"]').length >= count
                """, arg=target_count, timeout=10000)
            except:
                print(f"[Action] Warning: Image count sync timeout (curr={await get_uploaded_image_count(page)}, expected={target_count})")

            
        # 4. 最终提交 (click_submit 会处理后续的 loading 消失等待)
        return await click_submit(page)
    except Exception as e:
        print(f"[Action] submit_image_prompt error: {e}")
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

async def download_hd_image(page: Page, img_url: str, save_path: str, remove_wm: bool = True, max_attempts: int = 9):
    """下载高清图片 (精准 Hover 下载版)"""
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
                print(f"[Action] Hovering over image (attempt {attempt + 1}/{max_attempts})...")
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
                            print(f"[Action] Download button found: {sel}")
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
                        success, img_hash, p_stats = await _process_and_save(path, save_path, remove_wm)
                        if success:
                            p_stats["dl_time"] = dl_time
                            p_stats["mode"] = "hd"
                        return success, img_hash, p_stats
                
                # 如果没找到按钮且没到最后一次，继续重试
                if not is_last: continue
            except Exception as e:
                if is_last:
                    print(f"[Action] HD download failed after {max_attempts} attempts: {e}")
                else: 
                    print(f"[Action] Hover attempt {attempt+1} failed ({type(e).__name__}), retrying...")
        
    print("[Action] Falling back to direct request.")

    # 2. 备选方案：如果 Hover 失败或找不到按钮，通过 URL 直接下载
    success, h, stats = await download_q_image(page, img_url, save_path, remove_wm)
    if stats:
        stats["mode"] = "hd_fallback_q"
    return success, h, stats

async def download_q_image(page: Page, img_url: str, save_path: str, remove_wm: bool = True):
    """通过 URL 直接请求下载预览图 (快)"""
    stats = {}
    try:
        t_dl_start = time.time()
        response = await page.request.get(img_url)
        dl_time = round(time.time() - t_dl_start, 3)
        if response.ok:
            success, h, p_stats = await _process_and_save(BytesIO(await response.body()), save_path, remove_wm)
            if success:
                stats.update(p_stats)
                stats["dl_time"] = dl_time
                stats["mode"] = "preview"
            return success, h, stats
    except Exception as e:
        print(f"[Action] download_q_image failed: {e}")
    
    return False, None, stats

async def download_generated_images(
    page: Page, 
    remove_watermark: bool = True,
    download_mode: str = "preview"
) -> List[Dict[str, Any]]:
    """获取所有生成的图片 URL 并在对应的目录下批量处理"""
    urls = await get_generated_urls(page)
    if not urls:
        return []

    images_info = []
    output_base = Path("data/outputs")
    date_str = datetime.now().strftime("%Y%m%d")
    
    for i, url in enumerate(urls):
        save_dir = output_base / ("hd" if download_mode == "hd" else "q") / date_str
        save_dir.mkdir(parents=True, exist_ok=True)
        save_path = save_dir / f"temp_{int(time.time())}_{i}"
        
        if download_mode == "hd":
            success, img_hash, stats = await download_hd_image(
                page, url, str(save_path), remove_wm=remove_watermark
            )
        else:
            success, img_hash, stats = await download_q_image(
                page, url, str(save_path), remove_wm=remove_watermark
            )
        
        if success and img_hash:
            final_path = save_dir / f"{img_hash}.webp"
            temp_file = Path(str(save_path) + ".webp")
            if temp_file.exists():
                temp_file.rename(final_path)
            
            # 直接在 action 内打印详细统计
            raw_size = stats.get('raw_size_kb', 0)
            final_size = stats.get('size_kb', 0)
            ratio = round((final_size / raw_size * 100), 1) if raw_size > 0 else 0
            
            print(f"[Action] Download Meta: {img_hash} ({stats.get('mode', 'unknown')}) | "
                  f"Size: {raw_size}KB -> {final_size}KB ({ratio}%) | "
                  f"DL: {stats.get('dl_time', 0)}s | "
                  f"WM_Remove: {stats.get('wm_time', 0)}s | "
                  f"Save: {stats.get('save_time', 0)}s")

            images_info.append({
                "id": f"{date_str}/{img_hash}",
                "hash": img_hash,
                "date": date_str,
                "format": "webp",
                "url": url,
            })
            
    return images_info

async def _process_and_save(src: Any, dest: str, remove_wm: bool):
    """图片后处理内部函数"""
    stats = {}
    try:
        t_start = time.time()
        
        # 获取原始文件大小
        if isinstance(src, (str, Path)):
            raw_size = Path(src).stat().st_size
        elif hasattr(src, "getbuffer"):
            raw_size = src.getbuffer().nbytes
        elif hasattr(src, "seek"):
            src.seek(0, 2)
            raw_size = src.tell()
            src.seek(0)
        else:
            raw_size = 0
        stats["raw_size_kb"] = round(raw_size / 1024, 2)

        img = Image.open(src)
        
        if remove_wm:
            t_wm = time.time()
            # 将去水印这一 CPU 密集型操作放到线程池执行
            img = await asyncio.to_thread(WatermarkRemover.remove_watermark, img)
            stats["wm_time"] = round(time.time() - t_wm, 3)
        
        final_p = Path(dest).with_suffix(".webp")
        final_p.parent.mkdir(parents=True, exist_ok=True)
        
        t_save = time.time()
        # 将 WebP 编码这一极度吃 CPU 的操作放到线程池执行
        # 这能确保在保存大文件时，不会阻塞其他并发请求的调度
        await asyncio.to_thread(img.save, final_p, "WEBP", lossless=True)
        stats["save_time"] = round(time.time() - t_save, 3)
        
        stats["size_kb"] = round(final_p.stat().st_size / 1024, 2)
        
        with open(final_p, "rb") as f:
            h = base64.urlsafe_b64encode(hashlib.sha256(f.read()).digest()).decode().rstrip("=")
        
        stats["process_total"] = round(time.time() - t_start, 3)
        return True, h, stats
    except Exception as e:
        print(f"[Action] _process_and_save error: {e}")
        return False, None, stats

async def handle_consent_popups(page: Page, selectors: List[str] = _SELECTORS["agree_btns"]) -> bool:
    """处理各种同意弹窗"""
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
