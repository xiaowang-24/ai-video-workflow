"""Step 1 档案卡路由"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from models.schemas import ApiResponse
from services.openai_service import openai_service
from services.volcano_service import volcano_service
from services.cosyvoice_service import cosyvoice_service
from services.storage import storage_service
from app.config import ARCHIVES_DIR

router = APIRouter(prefix="/api/archive", tags=["archive"])

# 档案角度清单（code 与前端对齐）
CHARACTER_ANGLES = [
    ("front", "正脸", "正面特写镜头，平视，表情自然放松"),
    ("three_quarter", "3/4 侧脸", "三分之二侧面，展示五官立体感"),
    ("profile", "正侧面", "纯侧面剪影，展示下颌线、眉骨弧度"),
    ("full_body", "全身", "全身正面，自然站姿，展示完整服装"),
    ("half_body", "半身", "半身（胸部以上），可用于对话场景"),
    ("outfit", "服装细节", "服装细节特写，面料纹理、Logo、扣子等"),
]

PRODUCT_ANGLES = [
    ("front", "正面", "产品正面，平视，居中，纯色背景"),
    ("side", "侧面", "产品侧面，平视，展示厚度和侧面特征"),
    ("back", "背面", "产品背面，平视，展示背面特征"),
    ("top", "顶视", "产品顶视图，略俯视"),
    ("45_degree", "45°", "产品 45 度角，三维立体感"),
    ("detail", "细节", "Logo / 品牌名特写"),
]


def _load_archive(archive_id: str) -> dict:
    path = ARCHIVES_DIR / f"{archive_id}.json"
    if not path.exists():
        raise HTTPException(404, "档案卡不存在")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_archive(archive_id: str, data: dict):
    with open(ARCHIVES_DIR / f"{archive_id}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- GPT 不可用时的降级描述 ----------

_FALLBACK_CHARACTER = {
    "name": "未命名角色",
    "age_range": "未知",
    "gender": "未知",
    "ethnicity": "—",
    "hair": "（待 API 配置后自动分析）",
    "face_features": "（待 API 配置后自动分析）",
    "body_type": "（待 API 配置后自动分析）",
    "clothing": "（待 API 配置后自动分析）",
    "style_tags": [],
    "description": "【演示模式】配置 OPENAI_API_KEY 后，这里会自动生成 80-150 字的人物结构化描述（发型/五官/肤色/服装），作为视频生成的身份锚点。",
}

_FALLBACK_PRODUCT = {
    "name": "未命名产品",
    "category": "—",
    "color": "（待 API 配置后自动分析）",
    "material": "（待 API 配置后自动分析）",
    "shape": "（待 API 配置后自动分析）",
    "logo_text": "—",
    "distinctive_features": "（待 API 配置后自动分析）",
    "description": "【演示模式】配置 OPENAI_API_KEY 后，这里会自动生成 80-150 字的产品结构化描述（形状/颜色/材质/Logo 位置），确保视频里产品不变形。",
}

_FALLBACK_VOICE = {
    "gender": "未知",
    "age_range": "未知",
    "language": "zh",
    "description": "【演示模式】上传参考音频后，Step 4 配音时会用这段声音克隆音色。配置阿里百炼 CosyVoice 后可提声纹。",
}


def _safe(fn, fallback, **kwargs):
    try:
        return fn(**kwargs)
    except Exception as e:
        print(f"[llm-fallback] {getattr(fn, '__name__', fn)}: {e}")
        return fallback


@router.post("/create", response_model=ApiResponse)
async def create_archive_card(
    character_image: UploadFile = File(..., description="人物正面照"),
    product_image: UploadFile = File(..., description="产品正面图"),
    voice_audio: Optional[UploadFile] = File(None, description="参考音频 10-30 秒"),
    extra_description: str = Form("", description="补充说明"),
):
    """创建档案卡（multipart 直传文件）

    流程：保存文件 → GPT 分析描述 → 生成多角度参考图 → 声音指纹 → 持久化
    """
    archive_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()

    # 1. 保存上传文件
    char_info = storage_service.save_upload(
        await character_image.read(), character_image.filename or "character.jpg"
    )
    prod_info = storage_service.save_upload(
        await product_image.read(), product_image.filename or "product.jpg"
    )
    voice_info = None
    if voice_audio and voice_audio.filename:
        voice_info = storage_service.save_upload(
            await voice_audio.read(), voice_audio.filename
        )

    char_url = f"/uploads/{char_info['file_id']}"
    prod_url = f"/uploads/{prod_info['file_id']}"

    # 2. GPT-4o 分析（无 key 时自动降级）
    character_data = _safe(
        openai_service.analyze_character,
        _FALLBACK_CHARACTER,
        image_description=f"人物参考图已上传（本地路径 {char_url}）",
        extra=extra_description,
    )
    product_data = _safe(
        openai_service.analyze_product,
        _FALLBACK_PRODUCT,
        image_description=f"产品参考图已上传（本地路径 {prod_url}）",
        extra=extra_description,
    )
    voice_data = _safe(
        openai_service.analyze_voice,
        _FALLBACK_VOICE,
        audio_description=(
            f"参考音频已上传（{voice_info['filename'] if voice_info else '未上传'}）"
        ),
    )

    # 3. 生成多角度参考图（mock：本地 SVG 占位；真实：可灵 API）
    character_angles = []
    for code, label, angle_desc in CHARACTER_ANGLES:
        prompts = _safe(
            openai_service.generate_character_angles,
            {"prompt": f"{character_data['description']}, {angle_desc}", "negative_prompt": "deformed face, distorted"},
            character_desc=character_data["description"],
            angle=angle_desc,
        )
        try:
            url = volcano_service.kling_image_generate(
                prompt=prompts.get("prompt", ""),
                reference_image_url=char_url,
                negative_prompt=prompts.get("negative_prompt", ""),
                label=label,
                subject="character",
            )
        except Exception as e:
            print(f"[character {code}] 生成失败: {e}")
            url = None
        character_angles.append({"code": code, "label": label, "image_url": url})

    product_angles = []
    for code, label, angle_desc in PRODUCT_ANGLES:
        prompts = _safe(
            openai_service.generate_product_angles,
            {"prompt": f"{product_data['description']}, {angle_desc}", "negative_prompt": "deformed product, distorted logo"},
            product_desc=product_data["description"],
            angle=angle_desc,
        )
        try:
            url = volcano_service.kling_image_generate(
                prompt=prompts.get("prompt", ""),
                reference_image_url=prod_url,
                negative_prompt=prompts.get("negative_prompt", ""),
                label=label,
                subject="product",
            )
        except Exception as e:
            print(f"[product {code}] 生成失败: {e}")
            url = None
        product_angles.append({"code": code, "label": label, "image_url": url})

    # 4. 声音指纹（mock：文件名哈希）
    speaker_id = None
    if voice_info:
        try:
            speaker_id = cosyvoice_service.extract_voice_embedding(voice_info["local_path"])
        except Exception as e:
            print(f"[voice] 提取失败: {e}")

    # 5. 组装档案卡
    archive = {
        "archive_id": archive_id,
        "character": {
            **character_data,
            "source_image_url": char_url,
            "angles": character_angles,
        },
        "product": {
            **product_data,
            "source_image_url": prod_url,
            "angles": product_angles,
        },
        "voice": {
            **voice_data,
            "source_audio_url": f"/uploads/{voice_info['file_id']}" if voice_info else None,
            "speaker_id": speaker_id,
        },
        "created_at": now,
        "updated_at": now,
        "status": "draft",
    }

    _save_archive(archive_id, archive)

    return ApiResponse(success=True, message="档案卡创建成功", data=archive)


@router.get("/{archive_id}", response_model=ApiResponse)
async def get_archive_card(archive_id: str):
    data = _load_archive(archive_id)
    return ApiResponse(success=True, data=data)


@router.put("/{archive_id}", response_model=ApiResponse)
async def update_archive_card(archive_id: str, updates: dict):
    """用户编辑档案卡（修改描述、补充字段等）"""
    data = _load_archive(archive_id)
    for key in ["character", "product", "voice"]:
        if key in updates and isinstance(updates[key], dict):
            data[key].update(updates[key])
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_archive(archive_id, data)
    return ApiResponse(success=True, message="已更新", data=data)


@router.post("/{archive_id}/confirm", response_model=ApiResponse)
async def confirm_archive_card(archive_id: str):
    """用户确认档案卡（状态改为 confirmed，进入 Step 2）"""
    data = _load_archive(archive_id)
    data["status"] = "confirmed"
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_archive(archive_id, data)
    return ApiResponse(success=True, message="档案卡已确认", data=data)


@router.post("/{archive_id}/regenerate-character-angle/{angle_code}")
async def regenerate_character_angle(archive_id: str, angle_code: str):
    """重新生成人物某个角度的参考图"""
    data = _load_archive(archive_id)
    target = next(((c, l, d) for c, l, d in CHARACTER_ANGLES if c == angle_code), None)
    if not target:
        raise HTTPException(400, f"未知角度: {angle_code}")
    _, label, angle_desc = target

    try:
        prompts = _safe(
            openai_service.generate_character_angles,
            {"prompt": f"{data['character']['description']}, {angle_desc}", "negative_prompt": ""},
            character_desc=data["character"]["description"],
            angle=angle_desc,
        )
        new_url = volcano_service.kling_image_generate(
            prompt=prompts.get("prompt", ""),
            reference_image_url=data["character"].get("source_image_url"),
            negative_prompt=prompts.get("negative_prompt", ""),
            label=label,
            subject="character",
        )
        for a in data["character"].get("angles", []):
            if a["code"] == angle_code:
                a["image_url"] = new_url
                break
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_archive(archive_id, data)
        return ApiResponse(success=True, message="已重新生成", data=data)
    except Exception as e:
        raise HTTPException(500, f"重新生成失败: {e}")


@router.post("/{archive_id}/regenerate-product-angle/{angle_code}")
async def regenerate_product_angle(archive_id: str, angle_code: str):
    """重新生成产品某个角度的参考图"""
    data = _load_archive(archive_id)
    target = next(((c, l, d) for c, l, d in PRODUCT_ANGLES if c == angle_code), None)
    if not target:
        raise HTTPException(400, f"未知角度: {angle_code}")
    _, label, angle_desc = target

    try:
        prompts = _safe(
            openai_service.generate_product_angles,
            {"prompt": f"{data['product']['description']}, {angle_desc}", "negative_prompt": ""},
            product_desc=data["product"]["description"],
            angle=angle_desc,
        )
        new_url = volcano_service.kling_image_generate(
            prompt=prompts.get("prompt", ""),
            reference_image_url=data["product"].get("source_image_url"),
            negative_prompt=prompts.get("negative_prompt", ""),
            label=label,
            subject="product",
        )
        for a in data["product"].get("angles", []):
            if a["code"] == angle_code:
                a["image_url"] = new_url
                break
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_archive(archive_id, data)
        return ApiResponse(success=True, message="已重新生成", data=data)
    except Exception as e:
        raise HTTPException(500, f"重新生成失败: {e}")
