import asyncio
import httpx
import json
import os
import time
from io import BytesIO
from urllib.parse import urlparse

from PIL import Image

# ================= 配置 =================
# 目标接口地址
BASE_URL = "http://localhost:8000"

ENDPOINT = "/v1/images/edits"

# 比例到尺寸的映射
ASPECT_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "21:9": "2389x1024",
    "9:21": "1024x2389",
    "4:3": "1365x1024",
    "3:4": "1024x1365",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
}

# 基础测试配置
API_KEY = os.getenv("GEMINI2API_KEY", "sk-EnmbJerhazsSxW7S9hCSYhQH5sqN5xKfiFPT3RlAB6ukPhpP")
data_dir = os.getenv("DATA_DIR", "/app/data")
TEST_IMAGE_PATH = os.path.join(data_dir, "1.webp")
TARGET_RATIO = "16:9"  # 这里可以修改想要测试的比例
BASE_PROMPT = "Make it look like a cyberpunk city at night, neon lights"

# 压测配置（可通过环境变量覆盖）
TOTAL_REQUESTS = int(os.getenv("LOAD_TOTAL_REQUESTS", "20"))
CONCURRENCY = int(os.getenv("LOAD_CONCURRENCY", "10"))
REQUEST_TIMEOUT_SEC = int(os.getenv("LOAD_REQUEST_TIMEOUT_SEC", "180"))
HD_POLL_RETRIES = int(os.getenv("LOAD_HD_RETRIES", "60"))
HD_POLL_DELAY_SEC = float(os.getenv("LOAD_HD_DELAY_SEC", "2"))
OUTPUT_DIR = os.getenv("LOAD_OUTPUT_DIR", "/imagedata/deploy/nano_banana/test_image")
SAVE_PADDED_INPUT = os.getenv("LOAD_SAVE_PADDED_INPUT", "1") == "1"
# =======================================


def pad_image_to_ratio(img: Image.Image, ratio_str: str) -> Image.Image:
    """将图片扩充到指定比例，使用边缘像素填充。"""
    print(f"🔄 正在调整图片比例为 {ratio_str}...")

    try:
        rw, rh = map(float, ratio_str.split(":"))
        target_ratio = rw / rh
    except ValueError:
        print(f"⚠️ 无法解析比例 {ratio_str}，跳过处理")
        return img

    if img.mode != "RGB":
        img = img.convert("RGB")

    width, height = img.size
    current_ratio = width / height

    if current_ratio > target_ratio:
        new_width = width
        new_height = int(round(width / target_ratio))
    else:
        new_height = height
        new_width = int(round(height * target_ratio))

    if new_width == width and new_height == height:
        print("✅ 原图比例已匹配，无需扩充")
        return img

    new_img = Image.new("RGB", (new_width, new_height))
    x_offset = (new_width - width) // 2
    y_offset = (new_height - height) // 2
    new_img.paste(img, (x_offset, y_offset))

    if x_offset > 0:
        left_edge = img.crop((0, 0, 1, height)).resize((x_offset, height))
        right_edge = img.crop((width - 1, 0, width, height)).resize(
            (new_width - x_offset - width, height)
        )
        new_img.paste(left_edge, (0, y_offset))
        new_img.paste(right_edge, (x_offset + width, y_offset))

    if y_offset > 0:
        top_edge = img.crop((0, 0, width, 1)).resize((width, y_offset))
        bottom_edge = img.crop((0, height - 1, width, height)).resize(
            (width, new_height - y_offset - height)
        )
        new_img.paste(top_edge, (x_offset, 0))
        new_img.paste(bottom_edge, (x_offset, y_offset + height))

    print(f"✅ 图片已扩充: {width}x{height} -> {new_width}x{new_height}")
    return new_img


def build_request_params(image_bytes: bytes, req_id: int, size: str):
    prompt = f"{BASE_PROMPT}, aspect ratio {TARGET_RATIO}, load-test request {req_id}"
    data = {
        "prompt": prompt,
        "model": "gemini-pro",
        "n": "1",
        "size": size,
        "aspect_ratio": TARGET_RATIO,
        "response_format": "url",
        "download_mode": "hd",
    }
    files = {"images": (f"input_{req_id:04d}.webp", image_bytes, "image/webp")}
    return data, files


async def run_single_request(req_id, client, headers, semaphore, image_bytes, size):
    async with semaphore:
        start_ts = time.perf_counter()
        request_url = f"{BASE_URL}{ENDPOINT}"
        try:
            data, files = build_request_params(image_bytes, req_id, size)
            response = await client.post(request_url, data=data, files=files, headers=headers)
            response_text = response.text
            if response.status_code != 200:
                elapsed = time.perf_counter() - start_ts
                msg = f"接口失败 HTTP {response.status_code}: {response_text[:200]}"
                print(f"[{req_id:04d}] ❌ {msg}, elapsed: {elapsed:.2f}s")
                return {"ok": False, "req_id": req_id, "latency": elapsed, "error": msg}

            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                elapsed = time.perf_counter() - start_ts
                msg = f"JSON 解析失败: {exc}"
                print(f"[{req_id:04d}] ❌ {msg}, elapsed: {elapsed:.2f}s")
                return {"ok": False, "req_id": req_id, "latency": elapsed, "error": msg}

            items = payload.get("data", [])
            response_text_content = payload.get("text") or ""
            
            # [核心修改]：如果没有图片(data)但有文本(text)，不视为失败
            if not items and not response_text_content:
                elapsed = time.perf_counter() - start_ts
                msg = f"响应缺少 data 且无文本: {response_text[:200]}"
                print(f"[{req_id:04d}] ❌ {msg}, elapsed: {elapsed:.2f}s")
                return {"ok": False, "req_id": req_id, "latency": elapsed, "error": msg}

            raw_url = items[0].get("url") if items else ""
            elapsed = time.perf_counter() - start_ts
            
            log_msg = f"[{req_id:04d}] ✅ 成功 {elapsed:.2f}s"
            if raw_url:
                log_msg += f" -> {raw_url}"
            else:
                log_msg += " (仅文本)"
            
            # 无论是否有文本，都按照用户要求输出（无文本则显示空字符串）
            short_text = response_text_content.replace('\n', ' ')[:100]
            log_msg += f" | Text: {short_text}..."
            
            print(log_msg)
            return {
                "ok": True,
                "req_id": req_id,
                "latency": elapsed,
                "url": raw_url,
                "text": response_text_content
            }

        except httpx.TimeoutException:
            elapsed = time.perf_counter() - start_ts
            msg = f"请求超时 ({REQUEST_TIMEOUT_SEC}s)"
            print(f"[{req_id:04d}] ❌ {msg}, elapsed: {elapsed:.2f}s")
            return {"ok": False, "req_id": req_id, "latency": elapsed, "error": msg}
        except Exception as exc:
            elapsed = time.perf_counter() - start_ts
            msg = f"请求异常: {exc}"
            print(f"[{req_id:04d}] ❌ {msg}, elapsed: {elapsed:.2f}s")
            return {"ok": False, "req_id": req_id, "latency": elapsed, "error": msg}


def percentile(values, p: float) -> float:
    if not values:
        return 0.0
    idx = int(len(values) * p)
    idx = max(0, min(idx, len(values) - 1))
    return values[idx]


async def run_load_test():
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"❌ 错误: 找不到测试图片 {TEST_IMAGE_PATH}")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        with Image.open(TEST_IMAGE_PATH) as orig_img:
            padded_img = pad_image_to_ratio(orig_img, TARGET_RATIO)
            img_buffer = BytesIO()
            padded_img.save(img_buffer, format="WEBP")
            image_bytes = img_buffer.getvalue()

            if SAVE_PADDED_INPUT:
                preview_path = os.path.join(OUTPUT_DIR, "padded_input.webp")
                padded_img.save(preview_path)
                print(f"💾 预处理图片已保存: {preview_path}")
    except Exception as exc:
        print(f"❌ 图片处理失败: {exc}")
        return

    size = ASPECT_RATIO_TO_SIZE.get(TARGET_RATIO, "1024x1024")
    headers = {"Authorization": f"Bearer {API_KEY}"}
    semaphore = asyncio.Semaphore(CONCURRENCY)

    print("🚀 开始压测")
    print(f"  URL: {BASE_URL}{ENDPOINT}")
    print(f"  总请求数: {TOTAL_REQUESTS}")
    print(f"  并发数: {CONCURRENCY}")
    print(f"  目标比例: {TARGET_RATIO} -> size={size}")
    print(f"  输出目录: {OUTPUT_DIR}")

    limits = httpx.Limits(max_connections=CONCURRENCY * 2, max_keepalive_connections=CONCURRENCY)
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SEC)

    started = time.perf_counter()
    async with httpx.AsyncClient(limits=limits, timeout=timeout, verify=False) as client:
        tasks = [
            asyncio.create_task(
                run_single_request(i + 1, client, headers, semaphore, image_bytes, size)
            )
            for i in range(TOTAL_REQUESTS)
        ]
        results = await asyncio.gather(*tasks)
        total_elapsed = time.perf_counter() - started

    success = [x for x in results if x["ok"]]
    failed = [x for x in results if not x["ok"]]
    success_latency = sorted([x["latency"] for x in success])
    failed_latency = sorted([x["latency"] for x in failed])

    print("\n================ 压测结果 ================")
    print(f"总请求: {TOTAL_REQUESTS}")
    print(f"成功: {len(success)}")
    print(f"失败: {len(failed)}")
    print(f"总耗时: {total_elapsed:.2f}s")
    print(f"吞吐量: {TOTAL_REQUESTS / total_elapsed:.2f} req/s")

    if success_latency:
        avg = sum(success_latency) / len(success_latency)
        p50 = percentile(success_latency, 0.50)
        p95 = percentile(success_latency, 0.95)
        print(f"\n[成功请求] 平均延迟: {avg:.2f}s, P50: {p50:.2f}s, P95: {p95:.2f}s")
 
    if failed_latency:
        avg = sum(failed_latency) / len(failed_latency)
        p50 = percentile(failed_latency, 0.50)
        p95 = percentile(failed_latency, 0.95)
        print(f"[失败请求] 平均延迟: {avg:.2f}s, P50: {p50:.2f}s, P95: {p95:.2f}s")

    if failed:
        print("\n失败示例 (前 10 条):")
        for item in failed[:10]:
            print(f"  - req#{item['req_id']}: {item['error']} (elapsed: {item['latency']:.2f}s)")

    print("=========================================")


if __name__ == "__main__":
    asyncio.run(run_load_test())
