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
                tab_log(page, "Failed to submit image prompt", "error")
                await actions.dump_inspect(page, mode="full")
                await actions.dump_html(page)
                tab.status = BrowserStatus.SLEEP
                tab.sleep_until = datetime.now() + timedelta(minutes=9)
                return TaskResult(success=False, error="Failed to submit image prompt")

            # 4. 生成阶段
            tab.activity = "Generating images..."
            t2 = time.time()
            success = await actions.wait_for_results(page, timeout_s=119)
            durations["generate"] = round(time.time() - t2, 3)
            
            # 无论 wait_for_results 是否超时，都检查下是否有图片，或者是否有拒绝文本
            urls = await actions.get_generated_urls(page)
            if not urls:
                # 尝试获取拒绝文本
                refusal_text = await actions.get_last_response_text(page)
                if refusal_text:
                    tab_log(page, f"Gemini refused to generate images: {refusal_text}", "error")
                    await actions.dump_inspect(page, mode="full")
                    await actions.dump_html(page)
                    
                    # 检查是否是限额拒绝，若是则进入 2h 休眠模式
                    quota_keywords = ["无法为您生成更多图像", "无法为您创建更多图像", "can't generate more images", "can't create more images"]
                    if any(k in refusal_text for k in quota_keywords):
                        tab.status = BrowserStatus.SLEEP
                        tab.sleep_until = datetime.now() + timedelta(hours=2)
                        tab_log(page, f"Quota limit detected. Tab entering SLEEP mode until {tab.sleep_until.strftime('%H:%M:%S')}", "warning")
                    else:
                        # 普通拒绝/失败，进入 9 分钟休眠
                        tab.status = BrowserStatus.SLEEP
                        tab.sleep_until = datetime.now() + timedelta(minutes=9)
                        tab_log(page, f"Refusal detected. Tab entering cooldown SLEEP mode until {tab.sleep_until.strftime('%H:%M:%S')}", "warning")
                    
                    return TaskResult(success=False, error=f"Gemini refused: {refusal_text}")
                
                if not success:
                    tab_log(page, f"Timed out waiting for image results after {durations['generate']}s", "error")
                    await actions.dump_inspect(page, mode="full")
                    await actions.dump_html(page)
                    tab.status = BrowserStatus.SLEEP
                    tab.sleep_until = datetime.now() + timedelta(minutes=9)
                    return TaskResult(success=False, error="Timed out waiting for image results")
                
                tab_log(page, "No images found in response", "error")
                await actions.dump_inspect(page, mode="full")
                await actions.dump_html(page)
                tab.status = BrowserStatus.SLEEP
                tab.sleep_until = datetime.now() + timedelta(minutes=9)
                return TaskResult(success=False, error="No images found in response")

            # 5. 下载处理阶段
            tab.activity = "Downloading & Processing"
            t3 = time.time()
            background_work = None

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
                # 只有当确实成功下载了图片，才记录下载耗时（避免误导排查）
                if images_info:
                    durations["download"] = round(time.time() - t3, 3)

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
            
            return TaskResult(
                success=True, 
                data={"images": images_info, "date": datetime.now().strftime("%Y%m%d")},
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
