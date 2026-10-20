"""API 设置页：用户在网页填入 LLM / 视频 / 音频 三组 Key+地址+模型名

存本地 settings.json（不上传任何第三方），视频/音频模型适配器后接，先保存配置。

video.audio_mode：视频声音怎么来（"auto" 按模型能力自动判断 / "native" 强制用模型自带音频 / "tts" 强制后期配音）
"""
import json
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.schemas import ApiResponse
from app.config import SETTINGS_FILE
from services import model_catalog

router = APIRouter(prefix="/api/settings", tags=["settings"])

_DEFAULT = {
    "llm": {"enabled": False, "base_url": "", "api_key": "", "model": "gpt-4o"},
    "image": {"enabled": False, "base_url": "", "api_key": "", "model": ""},  # 与 LLM 共用时留空
    "video": {"enabled": False, "base_url": "", "api_key": "", "model": "", "audio_mode": "auto"},
    "audio": {"enabled": False, "base_url": "", "api_key": "", "model": ""},
}

# 允许的 audio_mode 取值
_AUDIO_MODES = ("auto", "native", "tts")


def _load() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            pass
    return {}


def _save(data: dict):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("", response_model=ApiResponse)
async def get_settings():
    data = _load()
    # 合并默认值（缺失分组补默认）
    for grp, default in _DEFAULT.items():
        if grp not in data or not isinstance(data[grp], dict):
            data[grp] = dict(default)
        else:
            for k, v in default.items():
                data[grp].setdefault(k, v)
    return ApiResponse(success=True, data=data)


class GroupSetting(BaseModel):
    enabled: Optional[bool] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    audio_mode: Optional[str] = None  # 仅 video 组使用


class SettingsUpdate(BaseModel):
    llm: Optional[GroupSetting] = None
    image: Optional[GroupSetting] = None
    video: Optional[GroupSetting] = None
    audio: Optional[GroupSetting] = None


@router.get("/video-models", response_model=ApiResponse)
async def video_models():
    """视频模型能力目录 + 帮助函数：前端据此提示每个模型是否支持原生音频。"""
    return ApiResponse(success=True, data={
        "catalog": model_catalog.catalog(),
    })


@router.post("/video-models/detect", response_model=ApiResponse)
async def detect_video_model(body: dict):
    """按模型名模糊判断音频能力（供前端实时徽章 / 后端 Step4 复用同一逻辑）。"""
    name = (body or {}).get("model", "")
    if not isinstance(name, str):
        raise HTTPException(status_code=400, detail="model 必须为字符串")
    return ApiResponse(success=True, data=model_catalog.detect(name))


@router.get("/image-models", response_model=ApiResponse)
async def image_models():
    """图像模型能力目录 + 帮助函数：前端据此提示每个模型在多视角生图上的能力。"""
    return ApiResponse(success=True, data={"catalog": model_catalog.catalog()["image"]})


@router.post("/image-models/detect", response_model=ApiResponse)
async def detect_image_model(body: dict):
    """按模型名模糊判断图像模型能力（供前端实时徽章 / 后端 Step1 复用同一逻辑）。"""
    name = (body or {}).get("model", "")
    if not isinstance(name, str):
        raise HTTPException(status_code=400, detail="model 必须为字符串")
    return ApiResponse(success=True, data=model_catalog.detect_image(name))


@router.put("", response_model=ApiResponse)
async def update_settings(body: SettingsUpdate):
    data = _load()
    patch = body.model_dump(exclude_none=True)
    for grp, values in patch.items():
        if not isinstance(values, dict):
            continue
        if grp not in data or not isinstance(data[grp], dict):
            data[grp] = {}
        for k, v in values.items():
            if v == "":
                continue
            # audio_mode 只接受白名单值
            if k == "audio_mode" and v not in _AUDIO_MODES:
                continue
            data[grp][k] = v
    _save(data)
    return ApiResponse(success=True, message="设置已保存", data=data)
