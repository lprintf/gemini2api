"""
OpenAI 兼容 API

提供与 OpenAI Images API 兼容的接口
"""

import uuid
import time
import hashlib
from datetime import datetime
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional, Literal
from pydantic import BaseModel
from pathlib import Path
import base64

from server.services.browser_pool import BrowserPool, BrowserStatus, RateLimitExceeded, NoAvailableTabs


router = APIRouter(prefix="/v1", tags=["OpenAI Compatible API"])


# 全局变量（稍后由 app.py 初始化）
browser_pool: Optional[BrowserPool] = None

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
async def check_rate_limit(request: Request, api_key: Optional[str] = Depends(verify_api_key)):
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
    image: Optional[UploadFile] = File(None, description="The image to edit (optional if image_path provided)"),
    image_path: Optional[str] = Form(None, description="Path to image: uploads/{date}/{hash}.{fmt} or outputs/hd/{date}/{hash}.{fmt}"),
    prompt: str = Form(..., description="A text description of the desired image edits"),
    model: str = Form("gemini-flash", description="Model to use: gemini-pro or gemini-flash"),
    n: int = Form(1, description="Number of images to generate"),
    size: str = Form("1024x1024", description="Image size (ignored, uses original size)"),
    response_format: Literal["url", "b64_json"] = Form("url", description="Response format"),
    api_key: str = Depends(check_rate_limit),
):
    """
    Create an edited or extended image given an original image and a prompt.

    Compatible with OpenAI Images API.

    Two ways to provide the image:
    1. Upload directly via `image` field (file upload)
    2. Use `image_path` field with path:
       - `uploads/{date}/{hash}.{fmt}` - from POST /v1/images/uploads
       - `outputs/hd/{date}/{hash}.{fmt}` - previously generated HD image

    Returns preview images immediately with URL format: `{date}/{hash}`.
    - Preview: `/outputs/q/{date}/{hash}.{fmt}`
    - HD: `/outputs/hd/{date}/{hash}.webp`

    Use GET /v1/images/hd/{date}/{hash} to check HD status.
    """
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    # 验证输入：必须提供 image 或 image_path
    if image is None and image_path is None:
        raise HTTPException(status_code=400, detail="Either 'image' or 'image_path' must be provided")

    # 获取可用浏览器
    browser = await browser_pool.get_available_browser()
    if browser is None:
        raise HTTPException(status_code=503, detail="No available browsers")

    task_id = f"task-{uuid.uuid4().hex[:12]}"

    # 确定输入图片路径
    if image_path:
        # 支持两种路径格式：
        # - uploads/{date}/{hash}.{fmt}
        # - outputs/hd/{date}/{hash}.{fmt}
        if image_path.startswith("uploads/"):
            input_path = Path(f"data/{image_path}")
        elif image_path.startswith("outputs/"):
            input_path = Path(f"data/{image_path}")
        else:
            raise HTTPException(status_code=400, detail="image_path must start with 'uploads/' or 'outputs/'")

        if not input_path.exists():
            raise HTTPException(status_code=404, detail=f"Image not found: {image_path}")
    else:
        # 保存上传的图片
        input_dir = Path(f"data/uploads/{task_id}")
        input_dir.mkdir(parents=True, exist_ok=True)

        input_path = input_dir / image.filename
        with open(input_path, "wb") as f:
            content = await image.read()
            f.write(content)

    # 转换模型名称
    gemini_model = "Pro" if "pro" in model.lower() else "Fast"

    try:
        # 执行快速预览任务
        result = await browser.execute_fast_task(
            task_id=task_id,
            input_image=str(input_path),
            prompt=prompt,
            model=gemini_model,
        )

        if not result or not result.get("images"):
            raise HTTPException(status_code=500, detail="Image edit failed")

        # 构造响应 - 返回 {date}/{hash} 格式的 URL
        created = int(time.time())
        data = []

        for img_info in result["images"]:
            if response_format == "url":
                # 返回 {date}/{hash} 格式，客户端可拼接完整路径
                # 预览图: /outputs/q/{date}/{hash}.{fmt}
                # 高清图: /outputs/hd/{date}/{hash}.webp
                data.append(ImageData(url=img_info['id']))
            else:  # b64_json
                # 读取预览图并编码为 base64
                preview_path = Path(f"data/outputs/q/{img_info['date']}/{img_info['hash']}.{img_info['format']}")
                with open(preview_path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode()
                data.append(ImageData(b64_json=image_data))

        return ImageEditResponse(created=created, data=data)

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
            headers={"Retry-After": str(e.retry_after)}
        )
    except NoAvailableTabs as e:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": str(e),
                    "type": "rate_limit_exceeded",
                    "code": "no_available_tabs",
                    "param": None,
                }
            },
            headers={"Retry-After": "5"}  # 建议5秒后重试
        )
    except KeyError as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"KeyError: {e} - available keys: {list(result.get('images', [{}])[0].keys()) if result else 'no result'}")
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
        raise HTTPException(status_code=404, detail=f"Image {date}/{file_hash} not found")

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
            detail="HD image is being downloaded in background. Please retry in a few seconds."
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
            status_code=202,
            detail=f"HD image status: {hd_status}. Please retry."
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
