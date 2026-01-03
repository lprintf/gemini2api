"""
OpenAI 兼容 API

提供与 OpenAI Images API 兼容的接口
"""

import uuid
import time
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional, Literal
from pydantic import BaseModel
from pathlib import Path
import base64

from server.services.browser_pool import BrowserPool, BrowserStatus
from server.services.rate_limiter import RateLimiter


router = APIRouter(prefix="/v1", tags=["OpenAI Compatible API"])


# 全局变量（稍后由 app.py 初始化）
browser_pool: Optional[BrowserPool] = None
rate_limiter: Optional[RateLimiter] = None


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
    image: UploadFile = File(..., description="The image to edit"),
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
    """
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    # 获取可用浏览器
    browser = await browser_pool.get_available_browser()
    if browser is None:
        raise HTTPException(status_code=503, detail="No available browsers")

    # 保存上传的图片
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    input_dir = Path(f"data/uploads/{task_id}")
    input_dir.mkdir(parents=True, exist_ok=True)

    input_path = input_dir / image.filename
    with open(input_path, "wb") as f:
        content = await image.read()
        f.write(content)

    # 转换模型名称
    gemini_model = "Pro" if "pro" in model.lower() else "Fast"

    try:
        # 执行任务
        result_paths = await browser.execute_task(
            task_id=task_id,
            input_image=str(input_path),
            prompt=prompt,
            model=gemini_model,
        )

        if not result_paths:
            raise HTTPException(status_code=500, detail="Image edit failed")

        # 构造响应
        created = int(time.time())
        data = []

        for path in result_paths:
            if response_format == "url":
                # 返回文件路径作为 URL（实际部署时应该返回 HTTP URL）
                data.append(ImageData(url=f"/outputs/{task_id}/{Path(path).name}"))
            else:  # b64_json
                # 读取图片并编码为 base64
                with open(path, "rb") as f:
                    image_data = base64.b64encode(f.read()).decode()
                data.append(ImageData(b64_json=image_data))

        return ImageEditResponse(created=created, data=data)

    except Exception as e:
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
