"""Project 中心路由：Step 0 创建 → Step 1 主资产 → Step 1.5 锁定

数据模型（项目级一致性引擎的单事实源）：
{
  "project_id": "…",
  "title": "…",
  "creative_brief": "…",        # 用户创意描述
  "target_duration": 30,        # 目标总时长（秒）
  "status": "created | assets_ready | assets_locked",
  "uploads": { "character_image_url": …, "product_image_url": …, "scene_image_url": …,
               "voice_audio_url": …, "music_url": …, "reference_video_url": … },
  "assets": {
     "CHAR_001":   {asset_id, type:"character", label, source_image_url, angles:[{code,label,image_url}],
                    desc:{…}, locked:false},
     "PROD_001":   {…},
     "SCENE_001":  {…},
     "VOICE_001":  {…}
  },
  "created_at": …, "updated_at": …
}
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from fastapi.responses import JSONResponse

from models.schemas import ApiResponse
from services.openai_service import openai_service
from services.image_service import image_service
from services.cosyvoice_service import cosyvoice_service
from services.storage import storage_service
from app.config import PROJECTS_DIR, UPLOADS_DIR

router = APIRouter(prefix="/api/projects", tags=["projects"])

# ---------- 资产定义 ----------

CHARACTER_ANGLES = [
    ("front", "正脸", "正面特写，平视，表情自然放松"),
    ("three_quarter", "3/4 侧", "三分之二侧面，展示五官立体感"),
    ("profile", "正侧面", "纯侧面剪影，下颌线、眉骨弧度"),
    ("full_body", "全身", "全身正面，自然站姿，完整服装"),
    ("half_body", "半身", "半身（胸部以上）"),
    ("outfit", "服装细节", "服装面料、Logo、扣子细节"),
]

PRODUCT_ANGLES = [
    ("front", "正面", "产品正面平视居中，纯色背景"),
    ("side", "侧面", "展示厚度与侧面特征"),
    ("back", "背面", "展示背面特征"),
    ("top", "顶视", "顶视图略俯视"),
    ("45_degree", "45°", "45 度角立体感"),
    ("logo", "Logo 特写", "品牌名/Logo 高清特写"),
]

SCENE_ANGLES = [
    ("establishing", "全景", "场景全貌，交代空间关系"),
    ("detail", "局部", "场景关键道具/角落"),
]

DEMO_MODE = "（演示模式）配置 API Key 后由 AI 自动生成。"  # 描述占位后缀

_FALLBACK_DESC = {
    "character": {
        "name": "未命名角色",
        "gender": "未知",
        "age_range": "未知",
        "hair": "待分析",
        "face_features": "待分析",
        "body_type": "待分析",
        "clothing": "待分析",
        "style_tags": [],
        "description": f"【人物资产】上传的人物正脸参考图。{DEMO_MODE}锁定后，所有镜头只允许引用此形象，禁止改变脸型/发型/五官/服装。",
    },
    "product": {
        "name": "未命名产品",
        "category": "待分析",
        "color": "待分析",
        "material": "待分析",
        "shape": "待分析",
        "logo_text": "待分析",
        "distinctive_features": "待分析",
        "description": f"【产品资产】上传的产品参考图。{DEMO_MODE}锁定后执行 A 级保护：Logo/包装文字/瓶体结构/颜色比例一律禁止改变。",
    },
    "scene": {
        "name": "未命名场景",
        "style": "待分析",
        "lighting": "待分析",
        "color_palette": "待分析",
        "props": [],
        "description": f"【场景资产】{DEMO_MODE}建议上传场景参考图（或 Step2 由 AI 根据创意生成场景描述后锁定）。",
    },
}


# ---------- 工具 ----------

def _now():
    return datetime.now(timezone.utc).isoformat()


def _project_path(pid: str):
    return PROJECTS_DIR / f"{pid}.json"


def _load_project(pid: str) -> dict:
    p = _project_path(pid)
    if not p.exists():
        raise HTTPException(404, "项目不存在")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_project(pid: str, data: dict):
    data["updated_at"] = _now()
    with open(_project_path(pid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _public_url(info: dict) -> Optional[str]:
    return f"/uploads/{info['file_id']}" if info else None


def _local_path(info: dict) -> Optional[str]:
    return info["local_path"] if info else None


def _safe(fn, fallback, **kwargs):
    try:
        r = fn(**kwargs)
        return r if isinstance(r, dict) else fallback
    except Exception as e:
        print(f"[llm-fallback] {getattr(fn, '__name__', str(fn))}: {e}")
        return fallback


def _angle_prompts(asset_type: str, desc_text: str, angle_desc: str) -> dict:
    """生成某角度的图像提示词：LLM 生成；无 key 降级为 资产描述+角度说明"""
    fallback = {"prompt": f"{desc_text}, {angle_desc}", "negative_prompt": "distorted, deformed"}
    if asset_type == "character":
        return _safe(openai_service.generate_character_angles, fallback,
                     character_desc=desc_text, angle=angle_desc)
    if asset_type == "product":
        return _safe(openai_service.generate_product_angles, fallback,
                     product_desc=desc_text, angle=angle_desc)
    return fallback


def _gen_angles(asset_type: str, source_url: Optional[str], desc_text: str):
    """为资产生成角度图（根据 API 设置自动选 Provider；无 Key 时降级 Mock）"""
    angle_specs = {
        "character": CHARACTER_ANGLES,
        "product": PRODUCT_ANGLES,
        "scene": SCENE_ANGLES,
    }.get(asset_type, [])
    angles = []
    for code, label, angle_desc in angle_specs:
        prompts = _angle_prompts(asset_type, desc_text or "", angle_desc)
        try:
            url = image_service["generate_angle_view"](
                front_image_url=source_url,
                angle_code=code,
                subject_type=asset_type,
                subject_description=prompts.get("prompt", ""),
                negative_prompt=prompts.get("negative_prompt", ""),
                label=label,
                angle_prompt=prompts.get("prompt", ""),
            )
        except Exception as e:
            print(f"[{asset_type}:{code}] 生成失败: {e}")
            url = None
        angles.append({"code": code, "label": label, "image_url": url})
    return angles


# ---------- Step 0：创建项目 ----------

@router.post("", response_model=ApiResponse)
async def create_project(
    character_image: UploadFile = File(..., description="人物正面照（必传）"),
    product_image: UploadFile = File(..., description="产品正面图（必传）"),
    scene_image: Optional[UploadFile] = File(None, description="场景参考图（可选）"),
    voice_audio: Optional[UploadFile] = File(None, description="参考音频（可选，用于克隆配音）"),
    music_audio: Optional[UploadFile] = File(None, description="背景音乐（可选）"),
    reference_video: Optional[UploadFile] = File(None, description="参考视频（可选）"),
    title: str = Form("未命名项目"),
    creative_brief: str = Form("", description="创意描述，如：女主在化妆台前使用精华液护肤…"),
    target_duration: int = Form(30, description="目标总时长（秒）"),
):
    pid = uuid.uuid4().hex[:12]

    async def _save(f):
        if f and f.filename:
            return storage_service.save_upload(await f.read(), f.filename)
        return None

    char_info = await _save(character_image)
    prod_info = await _save(product_image)
    scene_info = await _save(scene_image)
    voice_info = await _save(voice_audio)
    music_info = await _save(music_audio)
    video_info = await _save(reference_video)

    if not char_info or not prod_info:
        raise HTTPException(400, "人物照和产品图为必传项")

    project = {
        "project_id": pid,
        "title": title or "未命名项目",
        "creative_brief": creative_brief,
        "target_duration": max(5, int(target_duration)),
        "status": "created",
        "uploads": {
            "character_image_url": _public_url(char_info),
            "product_image_url": _public_url(prod_info),
            "scene_image_url": _public_url(scene_info),
            "voice_audio_url": _public_url(voice_info),
            "music_url": _public_url(music_info),
            "reference_video_url": _public_url(video_info),
            "_voice_local": _local_path(voice_info),
            "_scene_local": _local_path(scene_info),
        },
        "assets": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    _save_project(pid, project)
    return ApiResponse(success=True, message="项目已创建", data=_public_project(project))


# ---------- Step 1：生成主资产 ----------

@router.post("/{pid}/generate-assets", response_model=ApiResponse)
async def generate_assets(pid: str):
    """为项目生成主资产（CHAR_001 / PROD_001 / SCENE_001 / VOICE_001）"""
    project = _load_project(pid)
    up = project["uploads"]

    assets = {}

    # —— CHAR_001 人物 ——
    char_desc = _safe(
        openai_service.analyze_character,
        dict(_FALLBACK_DESC["character"]),
        image_description=f"人物参考图：{up.get('character_image_url')}",
        extra=project.get("creative_brief", ""),
    )
    assets["CHAR_001"] = {
        "asset_id": "CHAR_001",
        "type": "character",
        "label": "人物",
        "source_image_url": up.get("character_image_url"),
        "angles": _gen_angles("character", up.get("character_image_url"), char_desc.get("description", "")),
        "desc": char_desc,
        "locked": False,
    }

    # —— PROD_001 产品 ——
    prod_desc = _safe(
        openai_service.analyze_product,
        dict(_FALLBACK_DESC["product"]),
        image_description=f"产品参考图：{up.get('product_image_url')}",
        extra=project.get("creative_brief", ""),
    )
    assets["PROD_001"] = {
        "asset_id": "PROD_001",
        "type": "product",
        "label": "产品",
        "source_image_url": up.get("product_image_url"),
        "angles": _gen_angles("product", up.get("product_image_url"), prod_desc.get("description", "")),
        "desc": prod_desc,
        "protection": "A",  # A级：Logo/包装文字/瓶体/比例禁止改变
        "locked": False,
    }

    # —— SCENE_001 场景 ——
    scene_desc = _safe(
        openai_service.analyze_product,
        dict(_FALLBACK_DESC["scene"]),
        image_description=f"场景参考图：{up.get('scene_image_url') or '未上传（将由 AI 生成场景描述）'}",
        extra=project.get("creative_brief", ""),
    )
    if up.get("scene_image_url"):
        scene_angles = _gen_angles("scene", up.get("scene_image_url"), scene_desc.get("description", ""))
    else:
        scene_angles = []  # 无图：Step2 前可补图/补描述
    assets["SCENE_001"] = {
        "asset_id": "SCENE_001",
        "type": "scene",
        "label": "场景",
        "source_image_url": up.get("scene_image_url"),
        "angles": scene_angles,
        "desc": scene_desc,
        "locked": False,
    }

    # —— VOICE_001 声音 ——
    voice_source_url = up.get("voice_audio_url")
    speaker_id = None
    auto_generated = False
    voice_line = ""
    if up.get("_voice_local"):
        # 用户上传了参考音频 → 走克隆
        try:
            speaker_id = cosyvoice_service.extract_voice_embedding(up["_voice_local"])
        except Exception as e:
            print(f"[voice] 提取失败: {e}")
    else:
        # 用户未上传参考音频 → 系统用默认音色合成一段「示范台词」作为 VOICE_001
        auto_generated = True
        try:
            # 1) LLM 根据创意描述生成一句示范台词
            voice_line = _safe(
                openai_service.generate_voice_line,
                "今天给大家种草我自用的这款精华液。",
                brief=project["creative_brief"] or "护肤品日常分享",
                scene_hint="护肤品种草",
            )
            # 2) cosyvoice 用默认音色合成 wav
            wav_name = f"voice_auto_{uuid.uuid4().hex[:8]}.wav"
            wav_path = UPLOADS_DIR / wav_name
            cosyvoice_service.synthesize_default(voice_line, str(wav_path))
            voice_source_url = f"/uploads/{wav_name}"
            print(f"[voice] 自动生成参考音: {voice_line!r} → {wav_name}")
        except Exception as e:
            print(f"[voice] 自动生成失败（继续用默认音色）: {e}")
            voice_line = voice_line or "今天给大家种草我自用的这款精华液"

    voice_desc = _safe(
        openai_service.analyze_voice,
        {
            "gender": "女", "age_range": "未知", "language": "zh",
            "description": (
                f"系统默认音色（用户未上传参考音频）；示范台词：「{voice_line}」"
                if auto_generated and voice_line
                else (f"音色已克隆；Speaker: {speaker_id}" if speaker_id else f"【声音资产】{DEMO_MODE}")
            ),
        },
        audio_description=(
            "用户已上传参考音频" if up.get("_voice_local")
            else "用户未上传，系统根据创意描述自动生成了一段 4 秒默认音色参考音"
        ),
    )
    assets["VOICE_001"] = {
        "asset_id": "VOICE_001",
        "type": "voice",
        "label": "声音",
        "source_audio_url": voice_source_url,
        "speaker_id": speaker_id,
        "auto_generated": auto_generated,
        "sample_line": voice_line if auto_generated else None,
        "desc": voice_desc,
        "locked": False,
    }

    project["assets"] = assets
    project["status"] = "assets_ready"
    _save_project(pid, project)
    return ApiResponse(success=True, message="主资产已生成，请检查后锁定", data=_public_project(project))


# ---------- Step 1.5：锁定资产 ----------

@router.post("/{pid}/lock", response_model=ApiResponse)
async def lock_assets(pid: str):
    """锁定全部资产：锁定后只读，后续生成只准引用，禁止模型改动"""
    project = _load_project(pid)
    if project["status"] == "created":
        raise HTTPException(400, "请先生成主资产（generate-assets）")
    for a in project["assets"].values():
        a["locked"] = True
    project["status"] = "assets_locked"
    _save_project(pid, project)
    return ApiResponse(success=True, message="资产已锁定，进入 Step 2 镜头规划", data=_public_project(project))


# ---------- 查看 / 编辑 ----------

@router.get("", response_model=ApiResponse)
async def list_projects():
    items = []
    for f in PROJECTS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            items.append({"project_id": d["project_id"], "title": d.get("title"), "status": d.get("status"), "updated_at": d.get("updated_at")})
        except Exception:
            pass
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return ApiResponse(success=True, data=items)


@router.get("/{pid}", response_model=ApiResponse)
async def get_project(pid: str):
    return ApiResponse(success=True, data=_public_project(_load_project(pid)))


@router.put("/{pid}", response_model=ApiResponse)
async def update_project(pid: str, body: dict):
    """编辑项目字段（标题/创意/时长/资产描述文字）。锁定后的资产文字也可由用户在 Step2 前微调？锁定则拒绝改 asset 描述"""
    project = _load_project(pid)
    if "title" in body:
        project["title"] = body["title"]
    if "creative_brief" in body:
        project["creative_brief"] = body["creative_brief"]
    if "target_duration" in body:
        project["target_duration"] = max(5, int(body["target_duration"]))
    # 资产 desc 编辑（仅未锁定）
    edits = body.get("assets_edits") or {}
    if isinstance(edits, dict):
        for aid, patch in edits.items():
            if aid in project["assets"] and isinstance(patch, dict):
                asset = project["assets"][aid]
                if asset.get("locked"):
                    continue
                if "desc" in patch and isinstance(patch["desc"], dict):
                    asset["desc"].update(patch["desc"])
    _save_project(pid, project)
    return ApiResponse(success=True, message="已保存", data=_public_project(project))


@router.post("/{pid}/assets/{asset_id}/angles/{angle_code}/regenerate", response_model=ApiResponse)
async def regenerate_angle(pid: str, asset_id: str, angle_code: str):
    """单角度重新生成（失败回退：图不对→只重生成这一张，不影响其它）"""
    project = _load_project(pid)
    asset = project["assets"].get(asset_id)
    if not asset:
        raise HTTPException(404, f"资产不存在: {asset_id}")
    if asset.get("locked"):
        raise HTTPException(400, "资产已锁定，禁止修改（如需修改请新建项目）")
    spec_map = {"character": CHARACTER_ANGLES, "product": PRODUCT_ANGLES, "scene": SCENE_ANGLES}
    target = next(((c, l, d) for c, l, d in spec_map.get(asset["type"], []) if c == angle_code), None)
    if not target:
        raise HTTPException(400, f"未知角度: {angle_code}")
    _, label, angle_desc = target
    desc_text = asset["desc"].get("description", "") if isinstance(asset.get("desc"), dict) else ""
    prompts = {"prompt": f"{desc_text}, {angle_desc}", "negative_prompt": "distorted"}
    if asset["type"] in ("character", "product"):
        prompts = _safe(
            openai_service.generate_character_angles if asset["type"] == "character" else openai_service.generate_product_angles,
            prompts,
            **({"character_desc": desc_text} if asset["type"] == "character" else {"product_desc": desc_text}),
            angle=angle_desc,
        )
    url = image_service["generate_angle_view"](
        front_image_url=asset.get("source_image_url"),
        angle_code=angle_code,
        subject_type=asset["type"],
        subject_description=prompts.get("prompt", ""),
        negative_prompt=prompts.get("negative_prompt", ""),
        label=label,
        angle_prompt=prompts.get("prompt", ""),
    )
    for a in asset["angles"]:
        if a["code"] == angle_code:
            a["image_url"] = url
            break
    else:
        asset["angles"].append({"code": angle_code, "label": label, "image_url": url})
    _save_project(pid, project)
    return ApiResponse(success=True, message="已重新生成", data=_public_project(project))


@router.post("/{pid}/assets/{asset_id}/replace-source", response_model=ApiResponse)
async def replace_source(pid: str, asset_id: str, file: UploadFile = File(...)):
    """手动上传替换某资产的参考图，并重新生成该资产全部角度"""
    project = _load_project(pid)
    asset = project["assets"].get(asset_id)
    if not asset:
        raise HTTPException(404, f"资产不存在: {asset_id}")
    if asset.get("locked"):
        raise HTTPException(400, "资产已锁定，如需替换请先解锁（当前版请重新建项目）")
    info = storage_service.save_upload(await file.read(), file.filename or "replace.jpg")
    url = f"/uploads/{info['file_id']}"
    asset["source_image_url"] = url
    spec_map = {"character": CHARACTER_ANGLES, "product": PRODUCT_ANGLES, "scene": SCENE_ANGLES}
    desc_txt = asset["desc"].get("description", "") if isinstance(asset.get("desc"), dict) else ""
    asset["angles"] = _gen_angles(asset["type"], url, desc_txt)
    _save_project(pid, project)
    return ApiResponse(success=True, message="已替换并重新生成角度图", data=_public_project(project))


# ---------- 导出脱敏（移除本地路径等内部字段） ----------

def _public_project(project: dict) -> dict:
    import copy
    p = copy.deepcopy(project)
    up = p.get("uploads", {})
    for k in list(up.keys()):
        if k.startswith("_"):
            up.pop(k, None)
    return p
