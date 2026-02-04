"""
Gemini 标签页任务执行器 (Handlers)
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import actions
from server.core.database import get_db

from .exceptions import BrowserStatus
from .tab import TabInstance


async def reinitialize_tab(tab: TabInstance) -> bool:
    """重新初始化标签页（刷新页面并预热环境）"""
    print(f"[Tab {tab.browser_id}-{tab.tab_id}] Reinitializing...")
    tab.status = BrowserStatus.STARTING

    try:
        if tab.page:
            success = await actions.reinitialize_page(tab.page, model=tab.preferred_model)
            if success:
                tab.consecutive_failures = 0
                tab.status = BrowserStatus.IDLE
                print(f"[Tab {tab.browser_id}-{tab.tab_id}] Reinitialized successfully")
                return True
            else:
                tab.status = BrowserStatus.ERROR
                return False
        return False
    except Exception as e:
        print(f"[Tab {tab.browser_id}-{tab.tab_id}] Reinitialize failed: {e}")
        tab.status = BrowserStatus.ERROR
        return False


async def execute_task(
    tab: TabInstance, task_id: str, input_image: str, prompt: str, model: str = "Fast"
) -> Optional[List[str]]:
    """执行图片编辑任务"""
    if tab.status != BrowserStatus.IDLE:
        raise RuntimeError(f"Tab {tab.browser_id}-{tab.tab_id} is not idle (status: {tab.status})")

    print(f"[Tab {tab.browser_id}-{tab.tab_id}] Executing task {task_id}")
    tab.status = BrowserStatus.BUSY
    tab.current_task_id = task_id
    tab.last_active_at = datetime.now()

    start_time = time.time()
    result_paths = None
    error_message = None

    try:
        result = await actions.run_edit_pipeline(
            page=tab.page,
            input_image=input_image,
            prompt=prompt,
            output_dir="data/outputs/images",
            model=model,
        )

        if result:
            tab.total_tasks += 1
            tab.consecutive_failures = 0
            result_paths = result
        else:
            tab.failed_tasks += 1
            error_message = "No result returned"

        await finalize_task(tab, task_id, result_paths, error_message, start_time)
        return result

    except Exception as e:
        tab.failed_tasks += 1
        tab.consecutive_failures += 1
        print(f"[Tab {tab.browser_id}-{tab.tab_id}] Task {task_id} error: {e}")
        asyncio.create_task(reinit_after_error(tab))
        raise


async def reinit_after_error(tab: TabInstance):
    """错误后重新初始化"""
    tab.current_task_id = None
    await reinitialize_tab(tab)


async def finalize_task(
    tab: TabInstance, task_id: str, result_paths, error_message, start_time: float
):
    """完成任务后的清理和数据库更新"""
    tab.status = BrowserStatus.IDLE
    tab.current_task_id = None
    tab.last_active_at = datetime.now()
    duration = time.time() - start_time

    try:
        db = get_db()
        await db.update_task(
            task_id,
            {
                "browser_id": f"{tab.browser_id}-tab{tab.tab_id}",
                "status": "completed" if result_paths else "failed",
                "result_paths": result_paths,
                "error_message": error_message,
                "duration": duration,
                "completed_at": datetime.now(),
            },
        )
    except Exception as db_error:
        print(f"[Tab {tab.browser_id}-{tab.tab_id}] Failed to update DB: {db_error}")


async def execute_fast_task(
    tab: TabInstance,
    task_id: str,
    input_images: List[str],
    prompt: str,
    model: str = "Fast",
    output_dir: str = "data/outputs",
    remove_watermark: bool = True,
    download_mode: str = "both",
) -> Optional[Dict[str, Any]]:
    """执行快速预览任务"""
    if tab.status != BrowserStatus.IDLE:
        raise RuntimeError(f"Tab {tab.browser_id}-{tab.tab_id} is not idle (status: {tab.status})")

    print(f"[Tab {tab.browser_id}-{tab.tab_id}] Executing fast task {task_id}")
    tab.status = BrowserStatus.BUSY
    tab.current_task_id = task_id
    tab.last_active_at = datetime.now()

    base_output_dir = Path(output_dir)

    try:
        # 1. Pipeline 逻辑
        if not await actions.prepare_environment(tab.page, model=model):
            raise RuntimeError("Failed to prepare environment")
        if not await actions.upload_images_by_paste(tab.page, input_images):
            raise RuntimeError("Failed to upload images")
        if not await actions.input_prompt(tab.page, prompt):
            raise RuntimeError("Failed to input prompt")
        if not await actions.submit(tab.page):
            raise RuntimeError("Failed to submit generation")

        if not await actions.wait_for_generation(tab.page, timeout=120):
            print(f"[Tab {tab.browser_id}-{tab.tab_id}] Generation timeout, waiting extra 10s...")
            await asyncio.sleep(10)

        # 2. 下载逻辑
        date_str = datetime.now().strftime("%Y%m%d")
        images_info = []

        if download_mode == "hd":
            hd_dir = base_output_dir / "hd" / date_str
            hd_dir.mkdir(parents=True, exist_ok=True)
            image_urls = await actions.get_generated_image_urls(tab.page)
            if not image_urls:
                raise RuntimeError("No generated images found")

            for i, url in enumerate(image_urls):
                temp_path = hd_dir / f"temp_{i}.webp"
                success, hd_info = await actions.download_hd_by_url(
                    page=tab.page, url=url, save_path=str(temp_path), remove_watermark=remove_watermark
                )
                if success and hd_info:
                    file_hash = hd_info["hash"]
                    final_path = hd_dir / f"{file_hash}.webp"
                    temp_path.rename(final_path)
                    images_info.append({
                        "index": i, "hash": file_hash, "id": f"{date_str}/{file_hash}",
                        "date": date_str, "format": "webp", "path": str(final_path),
                        "size": hd_info["size"], "dimensions": hd_info["dimensions"],
                        "url": url, "is_hd": True,
                    })
            hd_status = "completed"
        else:
            image_urls = await actions.get_generated_image_urls(tab.page)
            if not image_urls:
                raise RuntimeError("No generated images found")
            preview_dir = base_output_dir / "q" / date_str
            preview_dir.mkdir(parents=True, exist_ok=True)

            for i, url in enumerate(image_urls):
                temp_path = preview_dir / f"temp_{i}.webp"
                success, file_hash = await actions.download_image_by_index(
                    page=tab.page, index=i, save_path=str(temp_path),
                    remove_watermark=remove_watermark, skip_hd=True
                )
                if success and file_hash:
                    final_path = preview_dir / f"{file_hash}.webp"
                    temp_path.rename(final_path)
                    images_info.append({
                        "index": i, "hash": file_hash, "id": f"{date_str}/{file_hash}",
                        "date": date_str, "format": "webp", "path": str(final_path),
                        "size": final_path.stat().st_size if final_path.exists() else 0,
                        "url": url,
                    })
            hd_status = "skipped" if download_mode == "preview" else "pending"

        if not images_info:
            raise RuntimeError("Failed to download any images")

        # 3. 元数据与后续逻辑
        meta_dir = base_output_dir / "meta" / date_str
        meta_dir.mkdir(parents=True, exist_ok=True)
        for img_info in images_info:
            meta = {
                "task_id": task_id, "browser_id": tab.browser_id, "tab_id": tab.tab_id,
                "created_at": datetime.now().isoformat(), "model": model,
                "prompt": prompt, "image": img_info, "hd_status": hd_status,
            }
            with open(meta_dir / f"{img_info['hash']}.json", "w") as f:
                json.dump(meta, f, indent=2)

        tab.total_tasks += 1
        if download_mode == "both":
            tab.status = BrowserStatus.DOWNLOADING_HD
            tab.hd_metadata = {"images": images_info, "date": date_str, "remove_watermark": remove_watermark}
            start_background_hd_download(tab, base_output_dir, model)
        else:
            tab.status = BrowserStatus.PREHEATING
            tab.current_task_id = None
            asyncio.create_task(preheat_after_skip(tab, model))

        return {"task_id": task_id, "images": images_info}

    except Exception as e:
        tab.failed_tasks += 1
        tab.consecutive_failures += 1
        try:
            error_dir = base_output_dir / "errors"
            error_dir.mkdir(parents=True, exist_ok=True)
            await tab.page.screenshot(path=str(error_dir / f"error_{tab.browser_id}_{tab.tab_id}_{datetime.now().strftime('%H%M%S')}.png"))
        except: pass
        tab.current_task_id = None
        asyncio.create_task(reinitialize_tab(tab))
        raise


def start_background_hd_download(tab: TabInstance, base_output_dir: Path, model: str):
    """启动后台高清下载"""
    async def _worker():
        if not tab.hd_metadata: return
        images = tab.hd_metadata["images"]
        date_str = tab.hd_metadata["date"]
        remove_watermark = tab.hd_metadata.get("remove_watermark", True)
        hd_dir = base_output_dir / "hd" / date_str
        hd_dir.mkdir(parents=True, exist_ok=True)
        meta_dir = base_output_dir / "meta" / date_str

        for img_info in images:
            try:
                success, hd_info = await actions.download_hd_by_url(
                    page=tab.page, url=img_info["url"],
                    save_path=str(hd_dir / f"{img_info['hash']}.webp"),
                    remove_watermark=remove_watermark,
                )
                update_meta_hd_status(
                    meta_dir / f"{img_info['hash']}.json",
                    "completed" if success else "failed",
                    hd_size=hd_info["size"] if success else 0,
                    hd_dimensions=hd_info["dimensions"] if success else ""
                )
            except:
                update_meta_hd_status(meta_dir / f"{img_info['hash']}.json", "failed")

        tab.status = BrowserStatus.PREHEATING
        await actions.prepare_environment(tab.page, model=model)
        tab.status = BrowserStatus.IDLE

    tab.hd_download_task = asyncio.create_task(_worker())


async def preheat_after_skip(tab: TabInstance, model: str):
    """跳过下载后的预热"""
    await actions.prepare_environment(tab.page, model=model)
    tab.status = BrowserStatus.IDLE


def update_meta_hd_status(meta_path: Path, status: str, **kwargs):
    """更新元数据状态"""
    try:
        if not meta_path.exists(): return
        with open(meta_path, "r") as f: meta = json.load(f)
        meta["hd_status"] = status
        meta.update(kwargs)
        with open(meta_path, "w") as f: json.dump(meta, f, indent=2)
    except: pass
