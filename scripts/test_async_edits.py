import asyncio
import httpx
import os
import time
from io import BytesIO
from PIL import Image

# ================= 配置 =================
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
API_KEY  = os.getenv("GEMINI2API_KEY", "sk-EnmbJerhazsSxW7S9hCSYhQH5sqN5xKfiFPT3RlAB6ukPhpP")
CONCURRENCY   = int(os.getenv("CONCURRENCY", "3"))          # 并发任务数
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3"))      # 轮询间隔（秒）
POLL_TIMEOUT  = int(os.getenv("POLL_TIMEOUT", "180"))       # 单任务最大等待（秒）
PROMPT = "Change the red background to a beautiful futuristic city landscape"
# e.g. CONCURRENCY=5 docker compose exec -e CONCURRENCY=5 gemini2api uv run python scripts/test_async_edits.py
# =========================================


def make_test_image_bytes() -> bytes:
    """生成一张红色的 100x100 PNG 测试图片"""
    img = Image.new("RGB", (100, 100), color="red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def upload_image(client: httpx.AsyncClient, headers: dict, img_bytes: bytes) -> str:
    """上传图片，返回 image_path"""
    files = {"image": ("test.png", img_bytes, "image/png")}
    resp = await client.post("/v1/images/uploads", files=files, headers=headers)
    resp.raise_for_status()
    return resp.json()["image_path"]


async def submit_async_edit(client: httpx.AsyncClient, headers: dict, image_path: str) -> str:
    """提交异步编辑，返回 task_id"""
    data = {
        "image_paths": f"uploads/{image_path}",
        "prompt": PROMPT,
        "model": "gemini-flash",
        "download_mode": "hd",
    }
    resp = await client.post("/v1/images/edits_async", data=data, headers=headers)
    resp.raise_for_status()
    return resp.json()["task_id"]


async def poll_task(client: httpx.AsyncClient, headers: dict, task_id: str, idx: int) -> dict:
    """轮询单个任务直到完成或超时"""
    start = time.time()
    retry = 0
    while True:
        elapsed = time.time() - start
        if elapsed > POLL_TIMEOUT:
            print(f"  [task#{idx} {task_id}] ⏰ 超时 ({POLL_TIMEOUT}s)")
            return {"ok": False, "task_id": task_id, "error": "timeout"}

        resp = await client.get(f"/v1/images/tasks/{task_id}", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        status = data["status"]
        retry += 1
        print(f"  [task#{idx} {task_id}] 第{retry}次 | {elapsed:.1f}s | {status}")

        if status == "completed":
            result = data.get("result") or {}
            urls = [item.get("url") for item in (result.get("data") or [])]
            print(f"  [task#{idx} {task_id}] ✅ 完成! URLs: {urls}")
            return {"ok": True, "task_id": task_id, "urls": urls}
        elif status == "failed":
            err = data.get("error")
            print(f"  [task#{idx} {task_id}] ❌ 失败: {err}")
            return {"ok": False, "task_id": task_id, "error": err}

        await asyncio.sleep(POLL_INTERVAL)


async def run_one(client: httpx.AsyncClient, headers: dict, img_bytes: bytes, idx: int) -> dict:
    """单个任务的完整流程"""
    try:
        image_path = await upload_image(client, headers, img_bytes)
        task_id = await submit_async_edit(client, headers, image_path)
        print(f"[task#{idx}] 🚀 已提交 task_id={task_id}")
        return await poll_task(client, headers, task_id, idx)
    except Exception as e:
        print(f"[task#{idx}] ❌ 异常: {e}")
        return {"ok": False, "error": str(e)}


async def main():
    print(f"🔧 并发数: {CONCURRENCY}  轮询间隔: {POLL_INTERVAL}s  超时: {POLL_TIMEOUT}s")
    img_bytes = make_test_image_bytes()
    headers = {"Authorization": f"Bearer {API_KEY}"}

    limits = httpx.Limits(max_connections=CONCURRENCY * 2, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0, limits=limits) as client:
        tasks = [run_one(client, headers, img_bytes, i + 1) for i in range(CONCURRENCY)]
        start = time.time()
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start

    ok = [r for r in results if r.get("ok")]
    fail = [r for r in results if not r.get("ok")]
    print(f"\n{'='*40}")
    print(f"总任务: {CONCURRENCY}  ✅ 成功: {len(ok)}  ❌ 失败: {len(fail)}  总耗时: {elapsed:.1f}s")
    if fail:
        print("失败详情:")
        for r in fail:
            print(f"  task_id={r.get('task_id')} error={r.get('error')}")
    print('='*40)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 已停止")

