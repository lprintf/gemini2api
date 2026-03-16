import asyncio
import base64
import hashlib
import time
import traceback
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
from playwright.async_api import Page
from server.utils.logger import tab_log, DATA_DIR
from .selectors import _SELECTORS, _AVATAR_PATTERN
from .base import click, input_prompt, select_menu_item, upload_image, get_uploaded_image_count
from .environment import handle_consent_popups
from ..remove_watermark.main import WatermarkRemover

async def start_new_chat(page: Page, selector: str = _SELECTORS["input_box"]) -> bool:
    """开启新对话（优化：如果已经是空白新对话则跳过 Ctrl+Shift+O，避免重置模型）"""
    try:
        if "/app" in page.url:
            # 先检查是否已经在空白新对话上（输入框存在 + 无已有对话内容）
            try:
                box = await page.wait_for_selector(selector, timeout=2000)
                if box:
                    has_responses = await page.query_selector('model-response, response-container')
                    if not has_responses:
                        tab_log(page, "Already on fresh chat, skipping Ctrl+Shift+O.")
                        return True
            except:
                pass
            # 页面上有旧对话内容，需要开新对话
            tab_log(page, "Stale chat detected, opening new chat...")
            await page.keyboard.press("Control+Shift+O")
        
        # 如果 URL 不对，强行跳转
        if "/app" not in page.url:
            await page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            
        # 检查输入框是否出现 (判定为成功)
        try:
            await page.wait_for_selector(selector, timeout=5000)
            return True
        except:
            # 兜底：尝试点击页面上的 New Chat 按钮 (针对快捷键失效的情况)
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
        # 等待渲染
        is_already_active = await page.wait_for_selector(already_active_selector, timeout=5000, state="visible")
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
                target = await page.wait_for_selector(f"{all_deselect}, {all_opt}", timeout=3000, state="visible")
                
                # 现在检查具体出现的是哪一个（必须是肉眼可见的，因为 Angular 组件可能会常驻 DOM 里隐藏）
                is_deselected = await page.query_selector(all_deselect)
                if is_deselected and await is_deselected.is_visible():
                    tab_log(page, "Tool menu opened, found tool is already active (deselect button visible).")
                    try:
                        await menu_btn.click(timeout=2000) # 收起菜单
                    except:
                        await menu_btn.click(timeout=3000, force=True)
                    return True
                    
                opt = await page.query_selector(all_opt)
                if opt and await opt.is_visible():
                    tab_log(page, "Tool menu opened, clicking tool to activate...")
                    try:
                        await opt.click(timeout=2000)
                    except:
                        await opt.click(timeout=3000, force=True)
                        
                    # 极其关键的护城河：等待 Angular 的组件重构（类似刷新）完成
                    # 只有当包含 "has-selected-item" 的外层工具按钮再次挂载并稳住，才说明大功告成
                    try:
                        await page.wait_for_selector(".toolbox-drawer-button.has-selected-item", timeout=5000, state="attached")
                        tab_log(page, "Tool activation confirmed (UI re-render completed).")
                    except:
                        tab_log(page, "Warning: Tool click executed, but UI activation state timeout.", "warning")
                        
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
            """, timeout=12000)
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
            if target_count == 0:
                tab_log(page, f"Submitting text prompt: '{prompt[:50]}...'")
            await input_prompt(page, prompt)
            
        if target_count > 0:
            tab_log(page, f"Waiting for image count to reach {target_count}...")
            try:
                await page.wait_for_function(f"""
                    (count) => document.querySelectorAll('img[src*="blob:"]').length >= count
                """, arg=target_count, timeout=35000)
            except:
                tab_log(page, f"Warning: Image count sync timeout (curr={await get_uploaded_image_count(page)}, expected={target_count})", "warning")

        # 记录提交前的容器数量 (model-response)
        initial_count = await page.evaluate("() => document.querySelectorAll('model-response, response-container, .model-response').length")
        
        # [针对 7-1 [0017] 优化]：检测提交后的 URL 变动
        submit_success = await click_submit(page)
        
        if submit_success:
            # 动态监测提交结果（最多等待 15.0s）
            timeout = 15.0
            start_wait = time.time()
            happy_counter = 0  # 信号稳定性计数器
            
            while time.time() - start_wait < timeout:
                state = await page.evaluate("""
                    () => {
                        const stopBtn = document.querySelector('.send-button.stop');
                        const editor = document.querySelector('.ql-editor.new-input-ui');
                        const count = document.querySelectorAll('model-response, response-container, .model-response').length;
                        const editorTrulyEmpty = editor && editor.innerText.trim() === '' && !editor.querySelector('img');
                        
                        let signal = null;
                        if (stopBtn && editorTrulyEmpty) signal = 'stop_and_empty';
                        else if (editorTrulyEmpty) signal = 'editor_empty';
                        else if (stopBtn) signal = 'stop_only';
                        
                        return { signal, count };
                    }
                """)
                
                signal = state['signal']
                current_count = state['count']
                
                # 判定 1: 容器数量增加 -> 绝对成功
                if current_count > initial_count:
                    tab_log(page, f"Submission confirmed: Container count increased ({initial_count} -> {current_count})")
                    return True
                
                # 判定 2: 信号稳定性检测 (需连续 3 次检测到成功信号，约 600ms)
                # 这能有效过滤由于 UI 重绘导致的瞬间 editor_empty 假象
                if signal in ('stop_and_empty', 'editor_empty'):
                    happy_counter += 1
                    if happy_counter >= 3:
                        tab_log(page, f"Submission confirmed: Stable signal detected ({signal})")
                        return True
                else:
                    happy_counter = 0
                
                # 判定 3: 只有 stop 按钮且持续超过 4s，也视为成功 (有些模式下编辑器清空很慢)
                if signal == 'stop_only' and (time.time() - start_wait > 4.0):
                    tab_log(page, "Submission confirmed: Persistent stop button detected.")
                    return True

                await asyncio.sleep(0.2)
            
            tab_log(page, f"Submission stuck (no stable signal/container increase) after {timeout}s. Failing fast.", "warning")
            return False # 视为本次提交失败，交给上层触发后台重排

        return submit_success
    except Exception as e:
        tab_log(page, f"submit_image_prompt error: {e}", "error")
        return False

async def wait_for_results(page: Page, timeout_s: int = 60, original_prompt: str = ""):
    """
    等待结果生成完成
    策略：
      - 检测到图片立即返回（成功路径）
      - 回复完成（isComplete && !isBusy）时返回
      - 仅在回复无图片、且文字字数维持稳定（3秒无变化）时才视为结束
      - 彻底移除单一的 hasSignificantText 长度判断，改为“动静态结合”判断
    """
    try:
        # 清除之前的状态（如果有）
        await page.evaluate("() => { window._gemini_wait_state = null; window._gemini_reverted = false; window._gemini_last_log_ts = Date.now(); }")
        
        # 对 Prompt 进行清理，用于精确比对（移除多余空格）
        clean_prompt = original_prompt.strip()
        
        await page.wait_for_function(f"""
            (targetPrompt) => {{
                const editor = document.querySelector('.ql-editor.new-input-ui');
                const stopBtn = document.querySelector('.send-button.stop');
                const isActuallyGenerating = !!stopBtn;

                // 1. [高精度回退检测] 
                // 使用模糊匹配：只要编辑器里的文本包含了我们发送的 Prompt，就判定为回退
                // 因为 Gemini 可能会加 "Image Edit: " 前缀，或者有微小的换行符差异
                if (editor && targetPrompt) {{
                    const currentText = editor.innerText.trim();
                    // 只要当前文本包含完整的原始 Prompt，且没有正在生成的迹象（或者编辑器看起来像是非活跃状态）
                    if (currentText.includes(targetPrompt)) {{
                        window._gemini_reverted = true;
                        window._gemini_revert_info = currentText; // 记录现场文本用于日志
                        return true; 
                    }}
                }}

                // 2. [错误弹窗检测] 
                const snackbar = document.querySelector('mat-snack-bar-container, .snack-bar, m-snackbar');
                if (snackbar) {{
                    const txt = snackbar.innerText.toLowerCase();
                    const errKeywords = ["something went wrong", "unable to", "failed", "violation", "safety", "content policy", "copyright", "无法", "错误", "失败"];
                    if (errKeywords.some(k => txt.includes(k))) {{
                        window._gemini_reverted = true; 
                        window._gemini_revert_info = `Snackbar: ${{txt}}`;
                        return true;
                    }}
                }}

                const containers = document.querySelectorAll('model-response, response-container, .model-response');
                if (containers.length === 0) return false;
                const last = containers[containers.length - 1];
                
                // 3. 成功路径：检测到图片
                const imgs = Array.from(last.querySelectorAll('img'));
                const hasImages = imgs.some(i => i.src.includes('googleusercontent'));
                if (hasImages) return true;

                // 4. 状态提取
                const mc = last.querySelector('message-content');
                const isBusy = (last.getAttribute('aria-busy') === 'true') || (mc && mc.getAttribute('aria-busy') === 'true');
                const footer = last.querySelector('.response-footer, response-footer');
                const isComplete = footer && footer.classList.contains('complete');

                // 获取当前文本长度
                let currentLen = 0;
                if (mc) {{
                    const clone = mc.cloneNode(true);
                    clone.querySelectorAll('.cdk-visually-hidden').forEach(el => el.remove());
                    currentLen = clone.innerText.trim().length;
                }}

                // 5. 稳定性检测逻辑
                if (!window._gemini_wait_state) {{
                    window._gemini_wait_state = {{ len: currentLen, ts: Date.now() }};
                }}
                
                const state = window._gemini_wait_state;
                if (currentLen !== state.len) {{
                    state.len = currentLen;
                    state.ts = Date.now();
                }}
                
                const stableTime = Date.now() - state.ts;
                const isStable = stableTime > 5000; 

                // 6. 返回判断
                if (!isActuallyGenerating && isComplete && !isBusy) {{
                    return true;
                }}

                if (!hasImages && currentLen > 10 && isStable && !isActuallyGenerating && !isBusy) {{
                    return true;
                }}
                
                return false;
            }}
        """, arg=clean_prompt, timeout=timeout_s * 1000)
        
        # 检查退出原因
        reverted = await page.evaluate("window._gemini_reverted === true")
        if reverted:
            # 捕获具体的现场信息
            revert_content = await page.evaluate("window._gemini_revert_info || 'Unknown'")
            tab_log(page, f"Silent rejection detected! Editor content: '{revert_content[:200]}...'. Failing fast.", "warning")
            return False

        tab_log(page, "Generation wait completed successfully.", "info")
        await asyncio.sleep(1.5)
        return True
    except Exception as e:
        tab_log(page, f"wait_for_results timeout or error: {e}", "warning")
        return False

async def get_last_response_text(page: Page) -> str:
    """获取最后一条回复的纯文本内容，用于诊断拒绝原因"""
    try:
        text = await page.evaluate("""
            () => {
                const containers = document.querySelectorAll('model-response, response-container, .model-response, [data-test-id="model-response"]');
                if (containers.length === 0) return "";
                const last = containers[containers.length - 1];
                
                // 移除视觉隐藏的结构化文本 (如 "Gemini 说")
                const hidden = last.querySelectorAll('.cdk-visually-hidden');
                hidden.forEach(el => el.remove());

                // 优先从 message-content 获取，避免混入头像等杂质
                const mc = last.querySelector('message-content, .message-content, .model-response-text');
                if (mc) return mc.innerText;

                // 尝试定位 markdown 面板或直接取 innerText
                const panel = last.querySelector('.markdown, .markdown-main-panel, .response-content');
                return panel ? panel.innerText : last.innerText;
            }
        """)
        return text.strip() if text else ""
    except:
        return ""

async def get_generated_urls(page: Page, max_wait_s: int = 12) -> List[str]:
    """获取生成的图片 URL 列表 (带有短时间的重试逻辑，防止加载延迟)"""
    start_time = time.time()
    while time.time() - start_time < max_wait_s:
        urls = await page.evaluate(f"""
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
        if urls:
            return urls
        
        # 如果还没发现 googleusercontent，但发现了 .image-button，说明还在加载中，继续等
        has_btn = await page.query_selector('.image-button, .image-preview')
        if not has_btn:
            # 如果连按钮都没发现，可能真的没有图片，但也等一下
            pass
            
        await asyncio.sleep(0.5)
        
    return []

async def download_hd_image(page: Page, img_url: str, remove_wm: bool = True, max_attempts: int = 3, is_disconnected: Optional[Any] = None):
    """下载高清图片 (精准 Hover 下载版，带 Snackbar 错误检测和快速失败)"""
    for attempt in range(max_attempts):
        is_last = (attempt == max_attempts - 1)
        # Check disconnection at the start of each retry
        if is_disconnected and callable(is_disconnected) and await is_disconnected():
            raise asyncio.CancelledError("Client disconnected during HD download loop")
            
        try:
            # 强化：每次尝试前都重新获取一次句柄，防止 DOM 变动导致之前的 handle 失效
            img_element = await page.evaluate_handle("""
                (url) => {
                    const containers = document.querySelectorAll('model-response, response-container, .model-response');
                    if (containers.length === 0) return null;
                    const last = containers[containers.length - 1];
                    // 模糊匹配：优先全匹配，其次匹配不带查询参数的部分
                    return Array.from(last.querySelectorAll('img')).find(i => i.src === url)
                        || Array.from(last.querySelectorAll('img')).find(i => i.src.split('=')[0] === url.split('=')[0]);
                }
            """, img_url)
            img_element = img_element.as_element()
            
            if not img_element:
                # 如果没找到句柄，尝试刷新一次 URL 列表（针对容器彻底刷新的情况）
                tab_log(page, f"Image handle lost, refreshing URLs (attempt {attempt+1})...")
                new_urls = await get_generated_urls(page, max_wait_s=3)
                if new_urls and img_url not in new_urls:
                    img_url = new_urls[0] 
                if is_last: break
                continue

            tab_log(page, f"Hovering over image (attempt {attempt + 1}/{max_attempts})...")
            await img_element.scroll_into_view_if_needed()
            try:
                await img_element.hover(timeout=3000)
            except:
                await img_element.dispatch_event("mouseenter")
            
            combined_selector = ', '.join([
                'button[aria-label*="Download"]',
                'button[aria-label*="下载"]',
                '.download-button',
                'button:has(mat-icon:has-text("download"))'
            ])
            try:
                download_btn = await page.wait_for_selector(combined_selector, timeout=3000, state="visible")
            except Exception:
                download_btn = None

            t_dl_start = time.time()
            try:
                async with page.expect_download(timeout=19000) as download_info:
                    if download_btn:
                        tab_log(page, "Attempting forced native click on download button...")
                        await download_btn.click(force=True)
                    else:
                        tab_log(page, "Native wait failed, attempting robust JS physical click fallback...")
                        clicked = await page.evaluate(f"""
                            (imgUrl) => {{
                                const containers = document.querySelectorAll('model-response, response-container, .model-response');
                                if (containers.length === 0) return {{ success: false, reason: "no containers" }};
                                const last = containers[containers.length - 1];
                                
                                let imgs = Array.from(last.querySelectorAll('img'));
                                let targetImg = imgs.find(i => i.src === imgUrl);
                                if (!targetImg && imgUrl) {{
                                    const base = imgUrl.split('=')[0].split('?')[0];
                                    targetImg = imgs.find(i => i.src.includes(base));
                                }}
                                if (!targetImg && imgs.length === 1) targetImg = imgs[0];
                                if (!targetImg) return {{ success: false, reason: "img not found", foundUrls: imgs.map(i=>i.src) }};
                                
                                let parent = targetImg.parentElement;
                                let btn = null;
                                for(let i=0; i<6; i++) {{
                                    if(!parent || parent === last) break;
                                    btn = parent.querySelector('{combined_selector}');
                                    if(btn) break;
                                    parent = parent.parentElement;
                                }}
                                
                                if (!btn) btn = last.querySelector('{combined_selector}');
                                
                                if(btn) {{
                                    btn.scrollIntoView();
                                    btn.click();
                                    return {{ success: true }};
                                }}
                                return {{ success: false, reason: "btn not found in parents or response container" }};
                            }}
                        """, img_url)
                        if not clicked.get("success"):
                            tab_log(page, f"JS Physical click failed: {{clicked.get('reason')}}", "warning")
                            raise TimeoutError(f"JS fallback failed: {{clicked.get('reason')}}")
                        else:
                            tab_log(page, "JS Physical click executed successfully.")

                    # 核心优化：在点击后的前 2 秒内高频监测 Snackbar，实现“秒级”快速失败
                    # 这不需要等到 expect_download 超时
                    for _ in range(4): # 0.5s * 4 = 2s
                        error_toast = await page.query_selector('mat-snack-bar-container, .snack-bar, m-snackbar')
                        if error_toast:
                            toast_text = await error_toast.inner_text()
                            if any(k in toast_text for k in ["无法下载", "can't download", "无法保存", "error"]):
                                tab_log(page, f"UI Error Toast detected: {toast_text.strip()}. Aborting wait.", "warning")
                                # 注意：这里不能简单 continue，因为 expect_download 还在运行
                                # 我们通过这种方式尽早跳出本次下载尝试
                                raise TimeoutError("Fast-fail due to UI Error Toast")
                        await asyncio.sleep(0.5)

                    tab_log(page, "Download button clicked, waiting for event...")

                download = await download_info.value
                dl_url = str(download.url) # 转换为字符串确保安全
                tab_log(page, f"Download event captured: {download.suggested_filename} | URL: {dl_url[:80]}...")
                
                if dl_url.startswith("blob:null"):
                    tab_log(page, f"Warning: Detected blob:null URL ({dl_url}). Gemini context might be isolated.", "error")

                failure = await download.failure() # 日志显示这是个协程，必须 await
                if failure:
                    tab_log(page, f"Download failure reported by browser: {failure}", "error")
                    continue
                    
                path = await download.path()
                dl_time = round(time.time() - t_dl_start, 3)
                if path:
                    buf = BytesIO(Path(path).read_bytes())
                    success, img_bytes, img_hash, p_stats = await _process_image(buf, remove_wm)
                    if success:
                        p_stats["dl_time"] = dl_time
                        p_stats["mode"] = "hd"
                        p_stats["hd_url"] = dl_url
                    return success, img_bytes, img_hash, p_stats
            except Exception as e:
                if "Fast-fail" in str(e):
                    tab_log(page, f"Attempt {attempt+1} aborted early: {e}")
                else:
                    tab_log(page, f"HD wait_for_download exception (attempt {attempt+1}): {str(e)}")
            
            if not is_last: continue
        except Exception as e:
            if is_last:
                tab_log(page, f"HD download critical failure: {e}", "error")
            else: 
                tab_log(page, f"Attempt {attempt+1} failed, retrying...", "warning")
                await asyncio.sleep(0.5)
        
    return False, None, None, {"error": "HD download failed after all attempts", "mode": "hd_failure"}


async def download_q_image(page: Page, img_url: str, remove_wm: bool = True, is_disconnected: Optional[Any] = None):
    """通过 URL 直接请求下载预览图 (纯内存处理)"""
    stats = {}
    try:
        if is_disconnected and callable(is_disconnected) and await is_disconnected():
            raise asyncio.CancelledError("Client disconnected during Q download")
            
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
        msg = f"download_q_image failed: {e}"
        tab_log(page, msg, "error")
        stats["error"] = msg
    return False, None, None, stats

async def download_generated_images(page: Page, remove_watermark: bool = True, download_mode: str = "preview", is_disconnected: Optional[Any] = None) -> List[Dict[str, Any]]:
    """获取所有生成的图片 URL 并下载处理（纯内存，直接用 hash 文件名落盘）"""
    urls = await get_generated_urls(page)
    if not urls: return []
    
    tab_log(page, f"Found {len(urls)} generated image URLs. Starting download ({download_mode})...")
    images_info = []
    output_base = Path("data/outputs")
    date_str = datetime.now().strftime("%Y%m%d")
    for i, url in enumerate(urls):
        try:
            if is_disconnected and callable(is_disconnected) and await is_disconnected():
                raise asyncio.CancelledError("Client disconnected during batch download")

            if download_mode == "hd":
                success, img_bytes, img_hash, stats = await download_hd_image(page, url, remove_wm=remove_watermark, is_disconnected=is_disconnected)
            else:
                success, img_bytes, img_hash, stats = await download_q_image(page, url, remove_wm=remove_watermark, is_disconnected=is_disconnected)
            
            if success and img_hash and img_bytes:
                save_dir = output_base / ("hd" if download_mode == "hd" else "q") / date_str
                save_dir.mkdir(parents=True, exist_ok=True)
                final_path = save_dir / f"{img_hash}.webp"
                final_path.write_bytes(img_bytes)
                raw_size = stats.get('raw_size_kb', 0)
                final_size = stats.get('size_kb', 0)
                ratio = round((final_size / raw_size * 100), 1) if raw_size > 0 else 0
                tab_log(page, f"[Img {i+1}/{len(urls)}] OK: {img_hash} | Size: {raw_size}K -> {final_size}K ({ratio}%) | DL: {stats.get('dl_time', 0)}s | Type: {stats.get('mode', 'unknown')}")
                images_info.append({"id": f"{date_str}/{img_hash}", "hash": img_hash, "date": date_str, "format": "webp", "url": url})
            else:
                tab_log(page, f"[Img {i+1}/{len(urls)}] Failed: {stats.get('error', 'Unknown error')} (URL: {url[:60]}...)", "error")
        except Exception as e:
            tab_log(page, f"[Img {i+1}/{len(urls)}] Critical download error: {str(e)}", "error")
    
    if not images_info and urls:
        tab_log(page, f"All {len(urls)} image download attempts failed.", "error")
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
        error_msg = f"Image processing failed: {str(e)}"
        tab_log(None, error_msg, "error") # tab_log fallback to print or if page is available... 
        # Actually _process_image doesn't have page.
        stats["error"] = error_msg
        return False, None, None, stats
