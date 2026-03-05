"""
OpenAI 兼容 API

提供与 OpenAI Images API 兼容的接口
"""

import base64
import hashlib
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from server.services.tasks import actions
from server.services.scheduler.pool import BrowserPool
from server.services.objects.exceptions import (
    BrowserStatus,
    NoAvailableBrowsers,
    NoAvailableTabs,
    RateLimitExceeded,
)

router = APIRouter(prefix="/v1", tags=["OpenAI Compatible API"])


# 全局变量（稍后由 app.py 初始化）
browser_pool: Optional[BrowserPool] = None
task_coordinator: Any = None

# 上传文件存储目录
UPLOAD_DIR = Path("data/uploads")


class ImageEditRequest(BaseModel):
    """图片编辑请求（JSON 格式，用于文档）"""

    prompt: str
    model: Optional[str] = "gemini-flash"
    n: Optional[int] = 1
    size: Optional[str] = "1024x1024"
    response_format: Optional[Literal["url", "b64_json"]] = "url"


class ImageData(BaseModel):
    """图片数据"""

    url: Optional[str] = None
    b64_json: Optional[str] = None


class ImageEditResponse(BaseModel):
    """图片编辑响应"""

    created: int
    data: list[ImageData]
    text: Optional[str] = None  # Gemini 回复的文字描述（图文混排时存在）


class TaskResponse(BaseModel):
    """任务响应"""

    id: str
    status: str
    created_at: int
    completed_at: Optional[int] = None
    result: Optional[ImageEditResponse] = None
    error: Optional[str] = None


class HDImageResponse(BaseModel):
    """高清图响应"""

    url: str
    size: int
    dimensions: str


# 依赖项：API Key 验证（接受但不验证，仅为保持 OpenAI 格式兼容）
async def verify_api_key(authorization: Optional[str] = Header(None)):
    """接受 API Key，但不进行验证（仅为 OpenAI API 格式兼容）"""
    # 如果提供了 authorization header，提取但不验证
    if authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:]  # 移除 "Bearer " 前缀
        return api_key

    # 如果没有提供，返回 None
    return None


# 依赖项：速率限制（针对浏览器实例）
async def check_rate_limit(
    request: Request, api_key: Optional[str] = Depends(verify_api_key)
):
    """
    检查浏览器实例的速率限制

    注意：速率限制是针对每个浏览器实例（登录账号）的，
    而不是针对 API Key 或 IP 地址的
    """
    # API key 仅用于格式兼容，不参与速率限制逻辑
    return api_key


@router.post("/images/edits", response_model=ImageEditResponse)
async def create_image_edit(
    request: Request,
    images: Optional[List[UploadFile]] = File(
        None, description="Images to edit (file uploads)"
    ),
    image_paths: Optional[str] = Form(
        None,
        description="Comma-separated paths to images: uploads/{date}/{hash}.{fmt} or outputs/hd/{date}/{hash}.{fmt}",
    ),
    prompt: str = Form(
        ..., description="A text description of the desired image edits"
    ),
    prompt_prefix: Optional[str] = Form(
        "Image Edit: ", description="Optional prefix to add to the prompt"
    ),
    model: str = Form(
        "gemini-flash", description="Model to use: gemini-pro or gemini-flash"
    ),
    n: int = Form(1, description="Number of images to generate"),
    size: str = Form(
        "1024x1024", description="Image size (ignored, uses original size)"
    ),
    response_format: Literal["url", "b64_json"] = Form(
        "url", description="Response format"
    ),
    download_mode: Literal["preview", "hd", "both"] = Form(
        "both",
        description="Download mode: preview (fast), hd (sync HD only), both (preview + background HD)",
    ),
    api_key: str = Depends(check_rate_limit),
):
    """
    Create an edited or extended image given an original image and a prompt.

    Compatible with OpenAI Images API.

    Ways to provide images:
    1. File uploads: `images` field (supports single or multiple files)
    2. Paths: `image_paths` field (comma-separated)

    Path formats:
    - `uploads/{date}/{hash}.{fmt}` - from POST /v1/images/uploads
    - `outputs/hd/{date}/{hash}.{fmt}` - previously generated HD image

    Download modes:
    - `preview`: Only download preview images (fastest response)
    - `hd`: Only download HD images (sync, slower but highest quality)
    - `both`: Download preview + background HD (default)

    Returns images with URL format: `{date}/{hash}`.
    - Preview: `/outputs/q/{date}/{hash}.webp`
    - HD: `/outputs/hd/{date}/{hash}.webp`
    """
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    # 收集所有输入图片路径
    input_paths: List[Path] = []
    task_id = f"task-{uuid.uuid4().hex[:12]}"

    # 1. 处理 image_paths（逗号分隔的路径）
    if image_paths:
        for p in image_paths.split(","):
            p = p.strip()
            if not p:
                continue
            if p.startswith("uploads/") or p.startswith("outputs/"):
                path = Path(f"data/{p}")
            else:
                raise HTTPException(status_code=400, detail=f"Invalid path format: {p}")
            if not path.exists():
                raise HTTPException(status_code=404, detail=f"Image not found: {p}")
            input_paths.append(path)

    # 2. 处理上传文件 images
    if images and not input_paths:
        input_dir = Path(f"data/uploads/{task_id}")
        input_dir.mkdir(parents=True, exist_ok=True)
        for i, img_file in enumerate(images):
            if img_file.filename:
                file_path = input_dir / f"{i}_{img_file.filename}"
                content = await img_file.read()
                with open(file_path, "wb") as f:
                    f.write(content)
                input_paths.append(file_path)

    # 验证至少有一个输入
    if not input_paths:
        raise HTTPException(
            status_code=400,
            detail="At least one image must be provided via 'images' or 'image_paths'",
        )

    # 转换模型名称
    gemini_model = "Pro" if "pro" in model.lower() else "Fast"

    # 添加可选的提示前缀
    if prompt_prefix:
        prompt = f"{prompt_prefix}{prompt}"

    try:
        # 使用协调者执行任务 (生成过程已包含资源调度)
        result_data = await task_coordinator.generate_images(
            prompt=prompt,
            input_images=[str(p) for p in input_paths],
            model=gemini_model,
            download_mode=download_mode,
            task_id=task_id
        )

        if not result_data.get("success"):
            raise HTTPException(status_code=500, detail=f"Image edit failed: {result_data.get('error')}")
        
        result = result_data

        # 构造响应 - 返回 {date}/{hash} 格式的 URL
        created = int(time.time())
        data = []

        for img_info in result["images"]:
            if response_format == "url":
                # 返回 {date}/{hash} 格式，客户端可拼接完整路径
                data.append(ImageData(url=img_info["id"]))
            else:  # b64_json
                # 读取预览图并编码为 base64
                preview_path = Path(
                    f"data/outputs/q/{img_info['date']}/{img_info['hash']}.{img_info['format']}"
                )
                with open(preview_path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode()
                data.append(ImageData(b64_json=image_data))

        response_text = result.get("text")
        return ImageEditResponse(created=created, data=data, text=response_text)

    except HTTPException:
        raise
    except RateLimitExceeded as e:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": str(e),
                    "type": "rate_limit_exceeded",
                    "code": "rate_limit_exceeded",
                    "param": None,
                    "retry_after": e.retry_after,
                }
            },
            headers={"Retry-After": str(e.retry_after)},
        )
    except (NoAvailableTabs, NoAvailableBrowsers) as e:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": str(e),
                    "type": "rate_limit_exceeded",
                    "code": "no_available_resources",
                    "param": None,
                }
            },
            headers={"Retry-After": "5"},  # 建议5秒后重试
        )
    except KeyError as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"KeyError: {e} - available keys: {list(result.get('images', [{}])[0].keys()) if result else 'no result'}",
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/images/tasks/{task_id}", response_model=TaskResponse)
async def get_task_status(
    task_id: str,
    authorization: Optional[str] = Header(None),
):
    """
    Get the status of an async image editing task.

    (For future async implementation)
    """
    # TODO: 实现任务队列和状态查询
    raise HTTPException(status_code=501, detail="Async tasks not implemented yet")


@router.get("/images/hd/{date}/{file_hash}", response_model=HDImageResponse)
async def get_hd_image(
    date: str,
    file_hash: str,
    authorization: Optional[str] = Header(None),
):
    """
    Get the high-resolution version of a preview image.

    HD images are downloaded automatically in the background after preview is returned.
    This endpoint checks if the HD version is ready and returns its URL.

    Args:
        date: The date directory (e.g., 20260107)
        file_hash: The hash of the preview image

    Returns:
        HDImageResponse with the HD image URL and metadata
    """
    import json

    # 读取图片元数据
    metadata_path = Path(f"data/outputs/meta/{date}/{file_hash}.json")
    if not metadata_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Image {date}/{file_hash} not found"
        )

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read metadata: {e}")

    # 检查 HD 状态
    hd_status = metadata.get("hd_status", "pending")

    if hd_status == "pending":
        # HD 下载尚未开始或正在进行
        raise HTTPException(
            status_code=202,
            detail="HD image is being downloaded in background. Please retry in a few seconds.",
        )
    elif hd_status == "failed":
        raise HTTPException(status_code=500, detail="HD image download failed")
    elif hd_status == "completed":
        # HD 已完成，返回路径
        return HDImageResponse(
            url=f"/outputs/hd/{date}/{file_hash}.webp",
            size=metadata.get("hd_size", 0),
            dimensions=metadata.get("hd_dimensions", "unknown"),
        )
    else:
        # 未知状态，可能还在下载中
        raise HTTPException(
            status_code=202, detail=f"HD image status: {hd_status}. Please retry."
        )


@router.get("/models")
async def list_models(authorization: Optional[str] = Header(None)):
    """
    List available models.

    Compatible with OpenAI API.
    """
    return {
        "data": [
            {
                "id": "gemini-pro",
                "object": "model",
                "created": 1677649800,
                "owned_by": "google",
            },
            {
                "id": "gemini-flash",
                "object": "model",
                "created": 1677649800,
                "owned_by": "google",
            },
        ]
    }


class UploadResponse(BaseModel):
    """上传响应"""

    image_path: str  # 格式: {date}/{hash}.{fmt}


@router.post("/images/uploads", response_model=UploadResponse)
async def upload_image(
    image: UploadFile = File(..., description="要上传的图片"),
):
    """
    上传图片到服务器

    返回图片路径 `{date}/{hash}.{fmt}`，后续可用于 /v1/images/edits 接口的 image_path 参数（需加前缀 uploads/）。
    前端可通过 `/uploads/{image_path}` 访问已上传的图片。
    """
    # 读取文件内容
    content = await image.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # 计算 hash（与图片编辑返回的格式一致：base64url 编码的 sha256）
    sha256_hash = hashlib.sha256(content).digest()
    file_hash = base64.urlsafe_b64encode(sha256_hash).decode().rstrip("=")

    # 获取文件扩展名
    original_name = image.filename or "image.png"
    ext = Path(original_name).suffix.lower() or ".png"
    if ext.startswith("."):
        ext = ext[1:]

    # 按日期组织目录
    date_str = datetime.now().strftime("%Y%m%d")
    upload_dir = UPLOAD_DIR / date_str
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件
    file_name = f"{file_hash}.{ext}"
    file_path = upload_dir / file_name

    with open(file_path, "wb") as f:
        f.write(content)

    # 返回相对路径: {date}/{hash}.{fmt}
    image_path = f"{date_str}/{file_hash}.{ext}"
    return UploadResponse(image_path=image_path)


class TestUploadResponse(BaseModel):
    """测试上传响应"""

    success: bool
    message: str
    uploaded_count: int
    actual_count: int  # 实际在页面上检测到的图片数


@router.post("/images/test-upload", response_model=TestUploadResponse)
async def test_playwright_upload(
    images: List[UploadFile] = File(..., description="要测试上传的图片列表"),
):
    """
    测试 Playwright 多图上传功能

    该接口用于验证 editor.upload_images_by_paste 是否正常工作。
    会获取一个浏览器标签页，准备环境，然后上传图片（但不提交生成）。
    """
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    if not images:
        raise HTTPException(status_code=400, detail="No images provided")

    # 保存上传的图片到临时目录
    task_id = f"test-{uuid.uuid4().hex[:12]}"
    input_dir = Path(f"data/uploads/{task_id}")
    input_dir.mkdir(parents=True, exist_ok=True)

    input_paths = []
    for i, img_file in enumerate(images):
        if img_file.filename:
            file_path = input_dir / f"{i}_{img_file.filename}"
            content = await img_file.read()
            with open(file_path, "wb") as f:
                f.write(content)
            input_paths.append(str(file_path))

    if not input_paths:
        raise HTTPException(status_code=400, detail="No valid images")

    # 获取可用浏览器 (指定 Fast 优先，因为测试上传不需要高性能模型)
    browser = await browser_pool.get_available_browser(model="Fast")
    if browser is None:
        raise HTTPException(status_code=503, detail="No available browsers")

    # 获取空闲标签页
    tab = browser.get_available_tab(model="Fast")
    if tab is None:
        raise HTTPException(status_code=503, detail="No available tabs")

    try:
        # 准备环境
        if not await actions.prepare_environment(tab.page, model="Fast"):
            raise HTTPException(status_code=500, detail="Failed to prepare environment")

        # 测试上传图片
        success = await actions.upload_images_by_paste(tab.page, input_paths)

        # 获取实际上传的图片数量
        actual_count = await actions.get_uploaded_image_count(tab.page)

        if success and actual_count >= len(input_paths):
            return TestUploadResponse(
                success=True,
                message=f"Successfully uploaded {len(input_paths)} image(s) via Playwright",
                uploaded_count=len(input_paths),
                actual_count=actual_count,
            )
        else:
            return TestUploadResponse(
                success=False,
                message=f"Upload reported success but actual count mismatch: expected {len(input_paths)}, got {actual_count}",
                uploaded_count=len(input_paths),
                actual_count=actual_count,
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload test failed: {e}")
    finally:
        # 启动后台重置，确保测试上传的图片被清理
        async def background_cleanup(t):
            try:
                await actions.reinitialize_page(t.page, model="Fast")
            finally:
                t.status = BrowserStatus.IDLE
        
        asyncio.create_task(background_cleanup(tab))
