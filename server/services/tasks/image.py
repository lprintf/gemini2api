import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Literal, Optional, Any, Dict
from .base import BaseEngineTask, TaskResult
from . import actions
from ..objects.exceptions import BrowserStatus
from server.utils.logger import get_tab_logger, tab_log

class ImageGenerationTask(BaseEngineTask):
    """图片生成与编辑任务（逻辑编排层）"""
    
    async def run(self, tab: Any) -> TaskResult:
        page = tab.page
        # 挂载 per-tab logger，actions 层通过 tab_log(page, msg) 使用
        page._logger = get_tab_logger(tab.browser_id, tab.tab_id)
                # 1. 提取参数
        prompt = self.payload.get("prompt")
        input_images = self.payload.get("input_images", [])
        if not input_images and self.payload.get("input_image"):
            input_images = [self.payload.get("input_image")]
            
        model = self.payload.get("model", "Fast")
        remove_watermark = self.payload.get("remove_watermark", True)
        download_mode = self.payload.get("download_mode", "preview")

        durations = {}
        start_ts = time.time()

        try:
            # 2. 准备阶段
            tab.activity = "Preparing environment"
            t0 = time.time()
            success = await actions.prepare_environment(page, model=model)
            durations["prepare"] = round(time.time() - t0, 3)
            if not success:
                tab_log(page, "Environment preparation failed", "error")
                await actions.dump_inspect(page, mode="full")
                await actions.dump_html(page)
                tab.status = BrowserStatus.SLEEP
                tab.sleep_until = datetime.now() + timedelta(minutes=9)
                return TaskResult(success=False, error="Environment preparation failed")

            # 3. 输入与提交阶段
            tab.activity = "Uploading and submitting"
            t1 = time.time()
            success = await actions.submit_image_prompt(
                page, prompt, image_paths=input_images
            )
            durations["submit"] = round(time.time() - t1, 3)
            if not success:
                tab_log(page, "Failed to submit image prompt (possible stuck UI)", "error")
                await actions.dump_inspect(page, mode="full")
                await actions.dump_html(page)
                
                # 直接返回失败，后台发起强制重排
                return TaskResult(
                    success=False, 
                    error="Failed to submit image prompt",
                    background_work=actions.reinitialize_page(page, model=model)
                )

            # 4. 生成阶段
            tab.activity = "Generating results..."
            t2 = time.time()
            # wait_for_results 会在大约 3 秒文本无变化或检测到图片时返回
            generation_success = await actions.wait_for_results(page, timeout_s=139 if model != "Fast" else 69)
            durations["generate"] = round(time.time() - t2, 3)
            
            # 第一优先级：获取文本（可能包含 Gemini 的成功描述或拒绝理由）
            response_text = await actions.get_last_response_text(page)
            
            # 第二优先级：尝试提取图片 URL
            # 如果文本已稳定但图片还没出来，get_generated_urls 会等待最多 12s
            urls = await actions.get_generated_urls(page)
            
            if not urls:
                # 情况 A：没有任何图片，我们需要根据文本判断是“拒绝”还是“仅文字成功”
                if response_text:
                    # 检查是否是限额拒绝，若是则进入 2h 休眠模式
                    quota_keywords = [
                        "无法为您生成更多图像", "无法为您创建更多图像",
                        "can't generate more images", "can't create more images",
                        "come back tomorrow", "can still find images from the web",
                    ]
                    if any(k in response_text for k in quota_keywords):
                        tab_log(page, f"Quota limit detected: {response_text}", "warning")
                        tab.status = BrowserStatus.SLEEP
                        tab.sleep_until = datetime.now() + timedelta(hours=2)
                        return TaskResult(success=False, error=f"Gemini quota exceeded: {response_text}")
                    
                    # 是否是其它类型的拒绝（如安全策略）
                    # 如果文本明显像是描述（例如包含 "Here is", "I have"), 则不视为拒绝
                    # 常规拒绝识别：由于用户要求“不要依赖文本内容”，除了确定的限额，其它的只要有字就算成功
                    tab_log(page, f"No images found, but text response received: {response_text[:100]}...", "info")
                    
                    # 虽然返回成功（符合用户“返回文本”的需求），但由于没出图，可能触发了某种软拦截或账号疲劳
                    # 进入 SLEEP 状态以冷却标签页，防止持续无图
                    tab.status = BrowserStatus.SLEEP
                    tab.sleep_until = datetime.now() + timedelta(minutes=9)
                    
                    return TaskResult(
                        success=True, 
                        data={"images": [], "text": response_text},
                        error=None
                    )
                
                # 情况 B：无图片也无文本，或者 wait_for_results 彻底超时
                if not generation_success:
                    tab_log(page, f"Timed out waiting for results after {durations['generate']}s", "error")
                    await actions.dump_inspect(page, mode="full")
                    await actions.dump_html(page)
                    
                    # 只有当超时且完全没出字，才考虑可能是 UI 状态卡死，触发后台重排
                    bg_work = None
                    if not response_text:
                        tab_log(page, "No response text found after timeout. Triggering background reinitialization...", "warning")
                        bg_work = actions.reinitialize_page(page, model=model)
                    else:
                        # 如果有字但超时了，可能只是生成慢，进入 9 分钟冷却即可
                        tab.status = BrowserStatus.SLEEP
                        tab.sleep_until = datetime.now() + timedelta(minutes=9)
                    
                    return TaskResult(success=False, error="Timed out waiting for results", background_work=bg_work)
                
                # 理论上不会走到这里（因为 wait_for_results 返回 True 代表有图或有稳定文字）
                return TaskResult(success=False, error="No results found (no images and no text)")

            # 5. 下载处理阶段 (已有图片链接)
            tab.activity = "Downloading & Processing"
            t3 = time.time()
            background_work = None
            
            # 记录发现的图片及附属文本
            tab_log(page, f"Found {len(urls)} images. Response text: {response_text[:50]}...")

            if download_mode == "both":
                # both 模式：先同步下载预览图（客户端等这个），HD 下载作为后台任务
                images_info = await actions.download_generated_images(
                    page, remove_watermark=remove_watermark, download_mode="preview"
                )
                durations["download_preview"] = round(time.time() - t3, 3)

                # 构建 HD 下载协程，交给 coordinator 后台执行
                async def bg_hd_download():
                    t_hd = time.time()
                    tab.activity = "Background HD download"
                    hd_images = await actions.download_generated_images(
                        page, remove_watermark=remove_watermark, download_mode="hd"
                    )
                    tab_log(page, f"Background HD download: "
                          f"{len(hd_images)} images in {time.time() - t_hd:.1f}s")

                background_work = bg_hd_download()
            else:
                # preview 或 hd 模式：正常同步下载
                images_info = await actions.download_generated_images(
                    page, remove_watermark=remove_watermark, download_mode=download_mode
                )
                durations["download"] = round(time.time() - t3, 3)

            # 统一校验：如果没有下载到任何图片信息，则视为失败（除非上面 Situation A 已提前返回）
            if not images_info:
                # 获取最后探测到的图片 URL 数量，用于更精确的报错
                urls = await actions.get_generated_urls(page)
                error_msg = f"Failed to process any generated images (Found {len(urls)} URLs but all failed)"
                tab_log(page, error_msg, "error")
                await actions.dump_inspect(page, mode="full")
                await actions.dump_html(page)
                tab.status = BrowserStatus.SLEEP
                tab.sleep_until = datetime.now() + timedelta(minutes=9)
                return TaskResult(success=False, error=error_msg)
            
            # 汇总结果数据（包含图文混排场景）
            result_data = {
                "images": images_info, 
                "date": datetime.now().strftime("%Y%m%d"),
                "text": response_text or "" # 确保即使为空也不是 None
            }
            if response_text:
                tab_log(page, f"Mixed response: {len(images_info)} images + text ({len(response_text)} chars)")

            return TaskResult(
                success=True, 
                data=result_data,
                metadata={"model": model, "prompt": prompt, "download_mode": download_mode},
                background_work=background_work
            )

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            tab_log(page, f"Task failed with exception: {str(e)}\n{error_trace}", "error")
            # 异常发生时自动捕获快照
            try:
                await actions.dump_inspect(page, mode="full")
                await actions.dump_html(page)
            except: pass
            
            tab.status = BrowserStatus.SLEEP
            tab.sleep_until = datetime.now() + timedelta(minutes=9)
            return TaskResult(success=False, error=str(e))
        finally:
            # 统一计算总耗时并打印已完成阶段的统计
            durations["total"] = round(time.time() - start_ts, 3)
            
            parts = []
            if "prepare" in durations: parts.append(f"Prepare: {durations['prepare']}s")
            if "submit" in durations: parts.append(f"Submit: {durations['submit']}s")
            if "generate" in durations: parts.append(f"Generate: {durations['generate']}s")
            # 兼容 download 或 download_preview
            dl_time = durations.get("download") or durations.get("download_preview")
            if dl_time: parts.append(f"Download: {dl_time}s")
            
            if parts:
                detail = ", ".join(parts)
                tab_log(page, f"Time Stats: Total {durations['total']}s ({detail})")
                
            tab.activity = "Idle"
