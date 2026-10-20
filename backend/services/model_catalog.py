"""模型能力目录（单一数据源）

分为两大板块：
1) 视频模型：Step 4 视频生成时判断该模型是否支持原生音视频
2) 图像模型：Step 1 多视角资产生成时判断该模型是否支持多参考生图（真 3D 一致性）

用户仍可自由填写任意模型名；本目录只是"智能提示 + 默认推荐"，不锁定选择。
"""

# 支持原生音视频的模型（判断依据：官方接口/文档确认输出带音轨）
NATIVE_AUDIO_MODELS = [
    {
        "name": "Veo 3 / 3.1（Google）",
        "example": "veo-3.1",
        "match": ["veo", "veo-3", "veo3"],
        "note": "原生音视频：对白+音效+环境声同步生成，支持参考图/多参考资产控制。",
    },
    {
        "name": "Sora 2（OpenAI）",
        "example": "sora-2",
        "match": ["sora", "sora-2"],
        "note": "原生音视频：画面与音频联合生成，含对白与环境声。",
    },
]

# 已知但默认不带原生音频的模型（出片为纯画面，声音需后期配音）
TTS_AUDIO_MODELS = [
    {
        "name": "可灵 Kling（火山引擎）",
        "example": "kling-v3",
        "match": ["kling", "可灵"],
        "note": "视频接口默认返回纯画面；是否带音轨以你实际调用的接口版本为准。",
    },
    {
        "name": "Seedance（火山引擎）",
        "example": "seedance-1.5-pro",
        "match": ["seedance", "seed"],
        "note": "出片默认纯画面，声音走后期配音。",
    },
    {
        "name": "即梦 Jimeng（字节）",
        "example": "jimeng-2.0",
        "match": ["jimeng", "即梦", "ji-meng"],
        "note": "部分新版本支持音效，默认按纯画面处理、后期配音。",
    },
    {
        "name": "混元 HunyuanVideo（腾讯）",
        "example": "hunyuan-video",
        "match": ["hunyuan", "混元", "hunyuanvideo"],
        "note": "出片默认纯画面，声音走后期配音。",
    },
]


def detect(model_name: str) -> dict:
    """根据用户填写的模型名，模糊匹配目录，返回能力判断。

    返回：
      {
        "known": bool,          # 是否被目录收录
        "native_audio": bool,   # 是否支持原生音视频（known=False 时为 None）
        "matched_name": str,    # 命中的目录条目展示名
        "note": str,            # 说明文案
      }
    """
    name = (model_name or "").strip().lower()
    if not name:
        return {"known": False, "native_audio": None, "matched_name": "", "note": "请先填写视频模型名"}

    for item in NATIVE_AUDIO_MODELS:
        if any(k in name for k in item["match"]):
            return {"known": True, "native_audio": True, "matched_name": item["name"], "note": item["note"]}

    for item in TTS_AUDIO_MODELS:
        if any(k in name for k in item["match"]):
            return {"known": True, "native_audio": False, "matched_name": item["name"], "note": item["note"]}

    return {
        "known": False,
        "native_audio": None,
        "matched_name": "",
        "note": "未收录的模型：请在右侧手动指定音频方式（如你的模型支持原生音视频，选“模型自带”即可）。",
    }


def catalog() -> dict:
    """返回完整目录，供前端设置页渲染模型提示列表。"""
    return {
        "native_audio": NATIVE_AUDIO_MODELS,
        "tts_audio": TTS_AUDIO_MODELS,
    }


def resolve_audio_mode(model_name: str, audio_mode: str = "auto") -> dict:
    """Step 4 视频生成前的最终裁决：该镜头声音怎么来？

    audio_mode 取值（用户在 API 设置页选择）：
      - "native" → 强制用模型自带音频（若模型不支持，返回 conflict=True 提示）
      - "tts"    → 强制后期配音（LLM 台词 + TTS）
      - "auto"   → 按模型能力自动判断（默认）

    返回：
      {
        "source": "native" | "tts",
        "mode": 用户设置的 audio_mode,
        "conflict": bool,   # native 强制但模型不支持 / 目录未知
        "reason": str,      # 人话解释，供前端/日志展示
      }
    """
    det = detect(model_name)
    mode = (audio_mode or "auto").strip().lower()

    if mode == "native":
        if det["known"] and det["native_audio"]:
            return {"source": "native", "mode": mode, "conflict": False,
                    "reason": f"{det['matched_name']} 支持原生音视频，随画面生成声音。"}
        return {"source": "tts", "mode": mode, "conflict": True,
                "reason": f"该模型未确认支持原生音频，强制 native 可能失败，已回退后期配音。{det['note']}"}

    if mode == "tts":
        return {"source": "tts", "mode": mode, "conflict": False,
                "reason": "用户指定强制后期配音：LLM 台词 + TTS。"}

    # auto：按模型能力
    if det["known"] and det["native_audio"]:
        return {"source": "native", "mode": mode, "conflict": False,
                "reason": f"自动判断：{det['matched_name']} 支持原生音视频，随画面生成声音。"}
    if det["known"]:
        return {"source": "tts", "mode": mode, "conflict": False,
                "reason": f"自动判断：{det['matched_name']} 出片为纯画面，走 LLM 台词 + TTS 配音。"}
    return {"source": "tts", "mode": mode, "conflict": False,
            "reason": "模型未收录：默认走后期配音；若你的模型带原生音频，请在设置里改选「只用模型自带音频」。"}


# ============================================================
# 图像模型能力目录（用于 Step 1 多视角资产生成）
# ============================================================

class ImageModelCapability:
    """图像模型在多视角资产生成上的能力等级"""
    MULTI_REF = "multi_ref"   # 多参考生图：真 3D 一致性最强
    IMAGE_GEN = "image_gen"   # 普通图生图 / 图编辑：依赖 prompt，一致性弱
    NOT_IMAGE = "not_image"   # 不是图像模型（聊天/TTS/嵌入 等）
    UNKNOWN   = "unknown"     # 未收录，无法判断


# 支持多参考生图（单图/多图 → 多角度一致图）
IMAGE_MULTIREF_MODELS = [
    {
        "name": "即梦多参考 Jimeng",
        "example": "jimeng-4.0",
        "match": ["jimeng", "即梦"],
        "note": "多参考生图：单图或多张参考图生成多角度一致图，真 3D 一致性最强。",
    },
    {
        "name": "Stable Diffusion + IP-Adapter / ControlNet",
        "example": "sdxl-ip-adapter",
        "match": ["sdxl", "stable-diffusion", "ip-adapter", "controlnet"],
        "note": "开源方案：IP-Adapter 锁定身份 + ControlNet 控制角度，可控但需本地 GPU。",
    },
    {
        "name": "Tripo3D / SV3D（3D 重建）",
        "example": "sv3d",
        "match": ["tripo", "sv3d", "stable-video-3d", "syncdreamer"],
        "note": "单图 → 3D 模型 → 多角度渲染，几何最准确，但较慢。",
    },
]

# 普通图像生成模型（图生图 / 文生图）
IMAGE_GEN_MODELS = [
    {
        "name": "DALL-E 3",
        "example": "dall-e-3",
        "match": ["dall-e", "dalle"],
        "note": "OpenAI 文生图 / 图编辑：角度靠 prompt 控制，一致性不如多参考模型。",
    },
    {
        "name": "GPT-Image-1",
        "example": "gpt-image-1",
        "match": ["gpt-image", "gptimage"],
        "note": "OpenAI 图像生成：支持 image edit，但角度控制依赖 prompt。",
    },
    {
        "name": "Midjourney",
        "example": "midjourney-v6",
        "match": ["midjourney", "mj"],
        "note": "文生图：角度靠 prompt 控制，支持 --sref 风格参考。",
    },
    {
        "name": "可灵图像 Kling-Image",
        "example": "kling-image-v1",
        "match": ["kling-image", "kling-v", "可灵图"],
        "note": "可灵图像：可灵视频同源，图生图能力，多视角一致性依赖参考图。",
    },
]

# 常见但“不是图像模型”的模型（防止用户把聊天模型误填到 image 组）
CHAT_ONLY_MODELS = [
    {
        "name": "DeepSeek Chat",
        "example": "deepseek-v4-pro",
        "match": ["deepseek"],
        "note": "这是大语言模型，不能生成图片；填到 image 组会被降级为演示模式。",
    },
    {
        "name": "GPT-4o / o1（聊天端点）",
        "example": "gpt-4o",
        "match": ["gpt-4", "gpt-4o", "o1-", "o3-"],
        "note": "聊天模型，不能走 /images/generations；填到 image 组会被降级为演示模式。",
    },
    {
        "name": "Claude / 通义千问 / 文心一言（聊天）",
        "example": "claude-3-5-sonnet",
        "match": ["claude", "qwen", "通义", "文心", "ernie"],
        "note": "大语言模型，不生成图片；填到 image 组会被降级为演示模式。",
    },
]


def detect_image(model_name: str) -> dict:
    """根据用户填写的图像模型名，判断其在多视角生图上的能力等级。

    返回：
      {
        "known": bool,
        "capability": "multi_ref" | "image_gen" | "not_image" | "unknown",
        "capability_label": str,  # 人话标签
        "matched_name": str,
        "note": str,
      }
    """
    name = (model_name or "").strip().lower()
    if not name:
        return {
            "known": False,
            "capability": ImageModelCapability.UNKNOWN,
            "capability_label": "未填写",
            "matched_name": "",
            "note": "请先填写图像模型名",
        }

    for item in IMAGE_MULTIREF_MODELS:
        if any(k in name for k in item["match"]):
            return {
                "known": True,
                "capability": ImageModelCapability.MULTI_REF,
                "capability_label": "多参考生图（真 3D 一致）",
                "matched_name": item["name"],
                "note": item["note"],
            }

    for item in IMAGE_GEN_MODELS:
        if any(k in name for k in item["match"]):
            return {
                "known": True,
                "capability": ImageModelCapability.IMAGE_GEN,
                "capability_label": "普通图生图",
                "matched_name": item["name"],
                "note": item["note"],
            }

    for item in CHAT_ONLY_MODELS:
        if any(k in name for k in item["match"]):
            return {
                "known": True,
                "capability": ImageModelCapability.NOT_IMAGE,
                "capability_label": "不是图像模型",
                "matched_name": item["name"],
                "note": item["note"],
            }

    return {
        "known": False,
        "capability": ImageModelCapability.UNKNOWN,
        "capability_label": "未收录",
        "matched_name": "",
        "note": "未收录的图像模型：系统会按 OpenAI 兼容 /images/generations 尝试调用。若失败则降级演示模式。",
    }


def catalog() -> dict:
    """返回完整目录，供前端设置页渲染模型提示列表。"""
    return {
        "video": {
            "native_audio": NATIVE_AUDIO_MODELS,
            "tts_audio": TTS_AUDIO_MODELS,
        },
        "image": {
            "multi_ref": IMAGE_MULTIREF_MODELS,
            "image_gen": IMAGE_GEN_MODELS,
            "not_image": CHAT_ONLY_MODELS,
        },
    }
