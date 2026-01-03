"""
Gemini API 兼容接口

提供与 Google Gemini API 兼容的接口格式
支持 generateContent 端点进行图片编辑/生成
"""

import uuid
import time
import base64
from fastapi import APIRouter, HTTPException, Header, Request
from typing import Optional, List, Literal
from pydantic import BaseModel
from pathlib import Path

from server.services.browser_pool import BrowserPool


router = APIRouter(prefix="/v1beta", tags=["Gemini Compatible API"])


# 全局变量（由 app.py 初始化）
browser_pool: Optional[BrowserPool] = None


# ============ 请求模型 ============

class InlineData(BaseModel):
    """内联数据（图片）"""
    mime_type: str  # e.g., "image/png", "image/jpeg", "image/webp"
    data: str  # base64 encoded image data


class Part(BaseModel):
    """内容部分"""
    text: Optional[str] = None
    inline_data: Optional[InlineData] = None
    inlineData: Optional[InlineData] = None  # 兼容驼峰命名


class Content(BaseModel):
    """内容"""
    parts: List[Part]
    role: Optional[str] = "user"


class GenerationConfig(BaseModel):
    """生成配置"""
    response_modalities: Optional[List[str]] = None  # ["TEXT", "IMAGE"]
    responseModalities: Optional[List[str]] = None  # 兼容驼峰命名
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_output_tokens: Optional[int] = None


class GenerateContentRequest(BaseModel):
    """generateContent 请求"""
    contents: List[Content]
    generation_config: Optional[GenerationConfig] = None
    generationConfig: Optional[GenerationConfig] = None  # 兼容驼峰命名


# ============ 响应模型 ============

class ResponseInlineData(BaseModel):
    """响应中的内联数据"""
    mimeType: str
    data: str


class ResponsePart(BaseModel):
    """响应部分"""
    text: Optional[str] = None
    inlineData: Optional[ResponseInlineData] = None


class ResponseContent(BaseModel):
    """响应内容"""
    parts: List[ResponsePart]
    role: str = "model"


class SafetyRating(BaseModel):
    """安全评分"""
    category: str
    probability: str


class Candidate(BaseModel):
    """候选响应"""
    content: ResponseContent
    finishReason: str = "STOP"
    index: int = 0
    safetyRatings: List[SafetyRating] = []


class UsageMetadata(BaseModel):
    """使用元数据"""
    promptTokenCount: int = 0
    candidatesTokenCount: int = 0
    totalTokenCount: int = 0


class GenerateContentResponse(BaseModel):
    """generateContent 响应"""
    candidates: List[Candidate]
    usageMetadata: Optional[UsageMetadata] = None
    modelVersion: Optional[str] = None


# ============ API 端点 ============

def extract_image_and_prompt(request: GenerateContentRequest) -> tuple[Optional[bytes], Optional[str], str]:
    """
    从请求中提取图片数据和文本提示

    Returns:
        (image_bytes, prompt, mime_type)
    """
    image_bytes = None
    prompt = None
    mime_type = "image/png"

    for content in request.contents:
        for part in content.parts:
            # 提取文本
            if part.text:
                prompt = part.text

            # 提取图片（支持两种命名风格）
            inline_data = part.inline_data or part.inlineData
            if inline_data:
                mime_type = inline_data.mime_type
                image_bytes = base64.b64decode(inline_data.data)

    return image_bytes, prompt, mime_type


def get_file_extension(mime_type: str) -> str:
    """根据 MIME 类型获取文件扩展名"""
    mime_to_ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mime_to_ext.get(mime_type, ".png")


@router.post("/models/{model_id}:generateContent", response_model=GenerateContentResponse)
async def generate_content(
    model_id: str,
    request: GenerateContentRequest,
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
    authorization: Optional[str] = Header(None),
):
    """
    Generate content using Gemini models.

    Compatible with Google Gemini API.

    Supported models:
    - gemini-2.0-flash-exp (uses Fast mode)
    - gemini-2.0-flash (uses Fast mode)
    - gemini-1.5-flash (uses Fast mode)
    - gemini-1.5-pro (uses Pro mode)
    - gemini-pro-vision (uses Pro mode)
    - imagen-3.0-generate-002 (uses Fast mode)
    """
    if browser_pool is None:
        raise HTTPException(status_code=500, detail="Browser pool not initialized")

    # 提取图片和提示词
    image_bytes, prompt, mime_type = extract_image_and_prompt(request)

    if not prompt:
        raise HTTPException(status_code=400, detail="No text prompt provided in request")

    # 获取可用浏览器
    browser = await browser_pool.get_available_browser()
    if browser is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": 503,
                    "message": "No available browsers. All browsers are busy or rate limited.",
                    "status": "UNAVAILABLE"
                }
            }
        )

    # 创建任务 ID
    task_id = f"gemini-{uuid.uuid4().hex[:12]}"

    # 如果有图片，保存到临时文件
    input_path = None
    if image_bytes:
        input_dir = Path(f"data/uploads/{task_id}")
        input_dir.mkdir(parents=True, exist_ok=True)

        ext = get_file_extension(mime_type)
        input_path = input_dir / f"input{ext}"
        with open(input_path, "wb") as f:
            f.write(image_bytes)

    # 确定模型模式
    gemini_model = "Fast"  # 默认使用 Fast
    if "pro" in model_id.lower():
        gemini_model = "Pro"

    try:
        # 执行任务
        result_paths = await browser.execute_task(
            task_id=task_id,
            input_image=str(input_path) if input_path else "",
            prompt=prompt,
            model=gemini_model,
        )

        if not result_paths:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "code": 500,
                        "message": "Image generation failed",
                        "status": "INTERNAL"
                    }
                }
            )

        # 构造响应
        response_parts = []

        # 添加生成的图片
        for path in result_paths:
            with open(path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()

            # 确定输出 MIME 类型
            output_ext = Path(path).suffix.lower()
            output_mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(output_ext, "image/png")

            response_parts.append(ResponsePart(
                inlineData=ResponseInlineData(
                    mimeType=output_mime,
                    data=image_data
                )
            ))

        # 可选：添加文本描述
        response_parts.append(ResponsePart(
            text=f"Generated {len(result_paths)} image(s) based on your prompt."
        ))

        return GenerateContentResponse(
            candidates=[
                Candidate(
                    content=ResponseContent(
                        parts=response_parts,
                        role="model"
                    ),
                    finishReason="STOP",
                    index=0,
                    safetyRatings=[]
                )
            ],
            usageMetadata=UsageMetadata(
                promptTokenCount=len(prompt.split()),
                candidatesTokenCount=10,
                totalTokenCount=len(prompt.split()) + 10
            ),
            modelVersion=model_id
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "code": 500,
                    "message": str(e),
                    "status": "INTERNAL"
                }
            }
        )


@router.get("/models")
async def list_models(
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
):
    """
    List available models.

    Compatible with Google Gemini API.
    """
    return {
        "models": [
            {
                "name": "models/gemini-2.0-flash-exp",
                "version": "2.0",
                "displayName": "Gemini 2.0 Flash Experimental",
                "description": "Fast image generation model",
                "inputTokenLimit": 1048576,
                "outputTokenLimit": 8192,
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-1.5-pro",
                "version": "1.5",
                "displayName": "Gemini 1.5 Pro",
                "description": "Pro image generation model",
                "inputTokenLimit": 2097152,
                "outputTokenLimit": 8192,
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-1.5-flash",
                "version": "1.5",
                "displayName": "Gemini 1.5 Flash",
                "description": "Fast image generation model",
                "inputTokenLimit": 1048576,
                "outputTokenLimit": 8192,
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/imagen-3.0-generate-002",
                "version": "3.0",
                "displayName": "Imagen 3",
                "description": "Image generation model",
                "inputTokenLimit": 480,
                "outputTokenLimit": 8192,
                "supportedGenerationMethods": ["generateContent"],
            },
        ]
    }


@router.get("/models/{model_id}")
async def get_model(
    model_id: str,
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
):
    """
    Get model details.

    Compatible with Google Gemini API.
    """
    models = {
        "gemini-2.0-flash-exp": {
            "name": f"models/{model_id}",
            "version": "2.0",
            "displayName": "Gemini 2.0 Flash Experimental",
            "description": "Fast image generation model",
            "inputTokenLimit": 1048576,
            "outputTokenLimit": 8192,
            "supportedGenerationMethods": ["generateContent"],
        },
        "gemini-1.5-pro": {
            "name": f"models/{model_id}",
            "version": "1.5",
            "displayName": "Gemini 1.5 Pro",
            "description": "Pro image generation model",
            "inputTokenLimit": 2097152,
            "outputTokenLimit": 8192,
            "supportedGenerationMethods": ["generateContent"],
        },
        "gemini-1.5-flash": {
            "name": f"models/{model_id}",
            "version": "1.5",
            "displayName": "Gemini 1.5 Flash",
            "description": "Fast image generation model",
            "inputTokenLimit": 1048576,
            "outputTokenLimit": 8192,
            "supportedGenerationMethods": ["generateContent"],
        },
    }

    # 移除 models/ 前缀
    clean_model_id = model_id.replace("models/", "")

    if clean_model_id not in models:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": 404,
                    "message": f"Model {model_id} not found",
                    "status": "NOT_FOUND"
                }
            }
        )

    return models[clean_model_id]
