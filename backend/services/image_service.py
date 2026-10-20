"""图像生成服务（多视角图 / 多参考生图）

设计原则：
1. 用户在「API 设置 → 图像模型」填什么模型，系统就接什么模型（不锁定厂商）
2. 无 Key 时降级到 MockProvider（演示模式，几何变换 + 视觉增强）
3. 通用接口 generate_angle_view，所有 Provider 实现同一签名
4. 多参考生图（真 3D 一致性）是特定模型的特殊能力，由 Provider 自己声明

Provider 类型（按用户填的 Base URL / Model 自动选择）：
- MockImageProvider                无 Key 兜底，本地几何变换
- JimengMultiRefProvider           即梦多参考（字节火山引擎，待 AK/SK）
- OpenAICompatibleImageProvider    任何 OpenAI 兼容 images API（DALL-E / GPT-Image / SD 兼容）
- CustomProvider                   用户自定义 Base URL（透传 POST 到 {base_url}/images/generations）
"""
from __future__ import annotations
import os
import re
import uuid
import json
import base64
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from app.config import settings, UPLOADS_DIR
from services import model_catalog


# ============================================================
# 角度 prompt 模板（每个 Provider 共用，根据 angle_code 拼最终描述）
# ============================================================
_ANGLE_PROMPTS = {
    "character": {
        "front":         "front-facing portrait, looking straight at camera, natural expression",
        "three_quarter": "three-quarter view, head turned 30 degrees, showing depth and dimension",
        "profile":       "perfect side profile view, head turned 90 degrees, sharp jawline and nose silhouette",
        "full_body":     "full body shot, head to toe, natural standing pose, full outfit visible",
        "half_body":     "half-body shot from chest up, balanced framing",
        "outfit":        "close-up of clothing details, fabric texture, logo, buttons visible",
    },
    "product": {
        "front":     "product front view, eye-level, centered, plain background",
        "side":      "product side view, showing thickness and profile shape",
        "back":      "product back view, showing rear features and labels",
        "top":       "top-down view of product, slight angle showing depth",
        "45_degree": "45-degree angle view, 3D depth perspective",
        "logo":      "extreme close-up of brand logo and label text, sharp and readable",
    },
    "scene": {
        "establishing": "wide establishing shot of the scene, full environment visible",
        "detail":       "scene detail close-up, focused on key props and atmosphere",
    },
    "costume": {
        "front":         "costume front view, laid flat or worn, full design visible",
        "three_quarter": "three-quarter view of the costume",
        "profile":       "side profile of the costume",
        "detail":        "close-up detail of fabric, embroidery, or accessories",
    },
}


def build_angle_prompt(subject_type: str, angle_code: str, subject_desc: str) -> str:
    """把 (主体, 角度) 拼成一段英文 prompt。供所有 Provider 使用。"""
    p = _ANGLE_PROMPTS.get(subject_type, {}).get(angle_code, "")
    desc = (subject_desc or "").strip().rstrip(".")
    return f"{desc}, {p}".strip(", ").strip() if desc else p


# ============================================================
# Provider 抽象接口
# ============================================================
class ImageProvider(ABC):
    name: str = "abstract"
    is_mock: bool = False

    @abstractmethod
    def generate_angle_view(
        self,
        front_image_url: Optional[str],
        angle_code: str,
        subject_type: str,           # character/product/scene/costume
        subject_description: str,
        angle_prompt: str,           # 已拼好的英文角度描述
        negative_prompt: str = "",
    ) -> str:
        """生成单个角度图，返回可访问的 URL(/uploads/xxx 或 http://...)"""
        ...


# ============================================================
# Mock Provider：本地几何变换 + 视觉增强（无 Key 时的演示模式）
# ============================================================
_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
]


def _load_font(size: int):
    from PIL import ImageFont
    for fp in _FONT_CANDIDATES:
        if fp.exists():
            try:
                return ImageFont.truetype(str(fp), size)
            except Exception:
                pass
    return ImageFont.load_default()


def _safe_filename_part(s: str) -> str:
    if not s:
        return "x"
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s).strip().strip(".")
    return re.sub(r"_+", "_", cleaned) or "x"


_ACCENTS = {
    "character": (236, 72, 153),
    "product":   (139, 92, 246),
    "scene":     (14, 165, 233),
    "costume":   (34, 197, 94),
}


# 角度预设（每种 subject_type 不同角度的几何变换参数）
_ANGLE_PRESETS = {
    "character": {
        # 真正"3D 一致"无法用纯几何变换达成，但可强化方向暗示（光影/透视/裁切）让观感更真
        "front":         {"rot": 0,   "scale": 1.00, "crop": None,           "mirror": False, "lighting": "center", "perspective": 0.0},
        "three_quarter": {"rot": -18, "scale": 1.05, "crop": None,           "mirror": False, "lighting": "left",   "perspective": 0.15},
        "profile":       {"rot": -6,  "scale": 1.10, "crop": "left_half",    "mirror": True,  "lighting": "side",   "perspective": 0.30},
        "full_body":     {"rot": 0,   "scale": 0.55, "crop": None,           "mirror": False, "lighting": "center", "perspective": 0.0},
        "half_body":     {"rot": 0,   "scale": 1.20, "crop": "upper_half",   "mirror": False, "lighting": "center", "perspective": 0.0},
        "outfit":        {"rot": 0,   "scale": 1.50, "crop": "mid_band",     "mirror": False, "lighting": "center", "perspective": 0.0},
    },
    "product": {
        "front":     {"rot": 0,   "scale": 1.00, "crop": None,            "mirror": False, "lighting": "center", "perspective": 0.0},
        "side":      {"rot": 90,  "scale": 1.00, "crop": None,            "mirror": False, "lighting": "left",   "perspective": 0.25},
        "back":      {"rot": 180, "scale": 1.00, "crop": None,            "mirror": False, "lighting": "center", "perspective": 0.0},
        "top":       {"rot": 0,   "scale": 1.40, "crop": "upper_third",   "mirror": False, "lighting": "top",    "perspective": 0.0},
        "45_degree": {"rot": 35,  "scale": 0.95, "crop": None,            "mirror": False, "lighting": "right",  "perspective": 0.35},
        "logo":      {"rot": 0,   "scale": 1.50, "crop": "center_half",   "mirror": False, "lighting": "center", "perspective": 0.0},
    },
    "scene": {
        "establishing": {"rot": 0,  "scale": 1.00, "crop": None,          "mirror": False, "lighting": "center", "perspective": 0.0},
        "detail":       {"rot": 0,  "scale": 1.30, "crop": "lower_right", "mirror": False, "lighting": "center", "perspective": 0.0},
    },
    "costume": {
        "front":         {"rot": 0,  "scale": 1.00, "crop": None,        "mirror": False, "lighting": "center", "perspective": 0.0},
        "three_quarter": {"rot": -22,"scale": 1.05, "crop": None,        "mirror": False, "lighting": "left",   "perspective": 0.15},
        "profile":       {"rot": -8, "scale": 1.10, "crop": "left_half", "mirror": True,  "lighting": "side",   "perspective": 0.25},
        "detail":        {"rot": 0,  "scale": 1.50, "crop": "mid_band",  "mirror": False, "lighting": "center", "perspective": 0.0},
    },
}


_CROP_REGIONS = {
    "upper_half":   (0,   0,   800, 400),
    "upper_third":  (0,   0,   800, 270),
    "left_half":    (0,   80,  400, 720),
    "center_half":  (200, 200, 600, 600),
    "mid_band":     (100, 300, 700, 600),
    "lower_right":  (400, 400, 800, 800),
}


def _fit_square(img, size: int = 800):
    """按比例缩放到 size 边长，灰色背景居中铺成方形"""
    from PIL import Image
    w, h = img.size
    s = size / max(w, h, 1)
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    img = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (245, 245, 247))
    canvas.paste(img, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def _apply_directional_lighting(img, direction: str):
    """根据光源方向叠加柔和的渐变阴影/高光，模拟 3D 立体感（演示模式增强）。

    注意：仅做轻微明暗变化，不能压黑主体。
    """
    from PIL import Image
    w, h = img.size
    overlay = Image.new("RGB", (w, h), (128, 128, 128))  # 中性灰

    for y in range(h):
        for x in range(w):
            # 计算归一化坐标
            nx, ny = x / max(w, 1), y / max(h, 1)
            if direction == "left":
                factor = 1 - nx * 0.35  # 左边亮
            elif direction == "right":
                factor = 0.65 + nx * 0.35  # 右边亮
            elif direction == "top":
                factor = 1 - ny * 0.30  # 顶部亮
            elif direction == "side":
                factor = 0.70 + (nx - 0.5) * 0.40  # 单侧强光影
            else:  # center
                factor = 1.0 - abs(nx - 0.5) * 0.15 - abs(ny - 0.5) * 0.10

            # 中性灰 (128) 上下浮动 ±30
            v = int(128 + (factor - 0.5) * 60)
            v = max(80, min(200, v))
            overlay.putpixel((x, y), (v, v, v))

    # 用 18% 透明度把 overlay 混合到原图：提亮/压暗都很轻
    return Image.blend(img, overlay, alpha=0.18)


def _apply_perspective_warp(img, strength: float):
    """错切/透视：让平面图略带"3D 倾斜"观感（用 Affine 错切，稳定兼容）"""
    if strength <= 0:
        return img
    from PIL import Image
    w, h = img.size
    # 错切矩阵：x' = x + strength * y, y' = y
    # Affine 变换参数：(a,b,c,d,e,f)
    shear = strength * 0.18
    coeffs = (1, shear, 0,
              0, 1, 0)
    return img.transform((w, h), Image.AFFINE, coeffs, resample=Image.BICUBIC, fillcolor=(245, 245, 247))


def _apply_preset(img, preset: dict):
    """根据预设对 800x800 方形图做几何 + 视觉增强"""
    from PIL import Image, ImageOps, ImageEnhance

    if preset.get("mirror"):
        img = ImageOps.mirror(img)

    # 透视变形（在旋转前做，避免裁切误差）
    persp = preset.get("perspective", 0.0)
    if persp:
        img = _apply_perspective_warp(img, persp)

    rot = preset.get("rot", 0)
    if rot:
        img = img.rotate(-rot if rot > 0 else rot, resample=Image.BICUBIC, fillcolor=(245, 245, 247))

    scale = preset.get("scale", 1.0)
    if scale < 1.0:
        new = int(800 * scale)
        small = img.resize((new, new), Image.LANCZOS)
        canvas = Image.new("RGB", (800, 800), (245, 245, 247))
        canvas.paste(small, ((800 - new) // 2, (800 - new) // 2))
        img = canvas
    elif scale > 1.0:
        new = int(800 * scale)
        big = img.resize((new, new), Image.LANCZOS)
        cx = (new - 800) // 2
        img = big.crop((cx, cx, cx + 800, cx + 800))

    crop_name = preset.get("crop")
    if crop_name and crop_name in _CROP_REGIONS:
        x1, y1, x2, y2 = _CROP_REGIONS[crop_name]
        img = img.crop((x1, y1, x2, y2)).resize((800, 800), Image.LANCZOS)

    # 方向光影（增强 3D 观感）
    lighting = preset.get("lighting", "center")
    img = _apply_directional_lighting(img, lighting)

    # 轻微色温调整（不同角度的光色不同）
    r, g, b = preset.get("tint", (1.0, 1.0, 1.0))
    if r != 1.0:
        img = ImageEnhance.Color(img).enhance(r)
    if g != 1.0:
        img = ImageEnhance.Brightness(img).enhance(g)
    if b != 1.0:
        img = ImageEnhance.Contrast(img).enhance(b)
    return img


def _add_overlay(img, label: str, accent_rgb, is_mock: bool):
    """叠加彩色边框 + 角度标签 + 演示水印"""
    from PIL import ImageDraw
    out = img.copy()
    draw = ImageDraw.Draw(out)
    draw.rectangle([(4, 4), (795, 795)], outline=accent_rgb, width=8)
    # 底部标签蒙版
    for y in range(640, 800):
        shade = int(60 * ((y - 640) / 160))
        draw.line([(0, y), (800, y)], fill=(shade, shade, shade))
    font_big = _load_font(46)
    font_small = _load_font(20)
    draw.text((32, 670), label, font=font_big, fill=(255, 255, 255))
    if is_mock:
        draw.text((32, 745), "演示模式 · 填 API Key 后由 AI 真生成", font=font_small, fill=(255, 220, 100))
    else:
        draw.text((32, 745), "AI 真生成 · 已锁定参考图", font=font_small, fill=(180, 255, 180))
    return out


class MockImageProvider(ImageProvider):
    """演示模式：对参考图做差异化几何 + 光影 + 透视变换，输出 6 张明显不同的角度图。
    真实 API 接入后由上层根据 settings 自动切换到 JimengMultiRefProvider 或 OpenAICompatibleImageProvider。"""

    name = "mock"
    is_mock = True

    def _resolve_local_path(self, reference_image_url: Optional[str]):
        if not reference_image_url:
            return None
        fname = reference_image_url.rstrip("/").split("/")[-1]
        for p in [UPLOADS_DIR / fname, UPLOADS_DIR / fname.lstrip("/")]:
            if p.exists():
                return p
        return None

    def _write_and_return(self, img, subject_type: str, label: str) -> str:
        safe = _safe_filename_part(label or "x")
        filename = f"mock_{subject_type}_{safe}_{uuid.uuid4().hex[:8]}.png"
        out_path = UPLOADS_DIR / filename
        img.save(out_path, "PNG", optimize=False)
        return f"/uploads/{filename}"

    def generate_angle_view(
        self,
        front_image_url: Optional[str],
        angle_code: str,
        subject_type: str,
        subject_description: str,
        angle_prompt: str,
        negative_prompt: str = "",
        label: str = "",
    ) -> str:
        from PIL import Image

        accent = _ACCENTS.get(subject_type, _ACCENTS["character"])
        src = self._resolve_local_path(front_image_url)

        # 无参考图：纯色占位
        if src is None:
            canvas = Image.new("RGB", (800, 800), (235, 235, 240))
            return self._write_and_return(canvas, subject_type, label or angle_code or "angle")

        try:
            src_img = Image.open(src)
            src_img.load()
        except Exception:
            canvas = Image.new("RGB", (800, 800), (235, 235, 240))
            return self._write_and_return(canvas, subject_type, label or angle_code or "angle")

        base = _fit_square(src_img, 800)
        preset = _ANGLE_PRESETS.get(subject_type, {}).get(angle_code or "")
        if preset:
            transformed = _apply_preset(base, preset)
        else:
            transformed = base

        # label: 中文角度名（如果前端传了）否则用 angle_code
        final = _add_overlay(transformed, label or angle_code or "angle", accent, is_mock=True)
        return self._write_and_return(final, subject_type, label or angle_code or "angle")


# ============================================================
# 真实 Provider 基类：通用 OpenAI 兼容图像生成 API
# ============================================================
class OpenAICompatibleImageProvider(ImageProvider):
    """通过 OpenAI 兼容接口（/images/generations 或 /images/edits）生成多视角图。

    适用：GPT-Image-1 / DALL-E 3 / Stable Diffusion (OpenAI 兼容模式) / 任何自定义代理。

    注意：通用 image-to-image 模型不支持严格的角度控制，效果取决于 prompt 描述。
    如需真 3D 一致性，建议在 settings 填即梦多参考 / Tripo3D 等专用模型。
    """
    name = "openai_compatible"
    is_mock = False

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def generate_angle_view(
        self,
        front_image_url: Optional[str],
        angle_code: str,
        subject_type: str,
        subject_description: str,
        angle_prompt: str,
        negative_prompt: str = "",
        label: str = "",
    ) -> str:
        # 1) 读参考图为 base64
        img_b64 = self._fetch_as_base64(front_image_url) if front_image_url else None

        # 2) 构造请求体（OpenAI 兼容 images/generations）
        prompt = angle_prompt or f"{subject_description}, {angle_code} view"
        body = {
            "model": self.model,
            "prompt": prompt + (f". Avoid: {negative_prompt}." if negative_prompt else ""),
            "n": 1,
            "size": "1024x1024",
        }
        if img_b64:
            # 部分 API 支持 image 参考：用 mask 或 reference 字段（如有）
            body["image"] = f"data:image/png;base64,{img_b64}"

        # 3) POST
        req = urllib.request.Request(
            f"{self.base_url}/images/generations",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")[:500]
            raise RuntimeError(f"图像生成 API 返回 {e.code}: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"图像生成 API 调用失败: {e}") from e

        # 4) 解析返回（OpenAI 格式：data[0].url 或 data[0].b64_json）
        data = payload.get("data") or []
        if not data:
            raise RuntimeError(f"图像生成返回空: {json.dumps(payload)[:300]}")
        item = data[0]
        if "url" in item:
            return item["url"]
        if "b64_json" in item:
            raw = base64.b64decode(item["b64_json"])
            fname = f"ai_{_safe_filename_part(subject_type)}_{_safe_filename_part(angle_code)}_{uuid.uuid4().hex[:8]}.png"
            out_path = UPLOADS_DIR / fname
            out_path.write_bytes(raw)
            return f"/uploads/{fname}"
        raise RuntimeError(f"图像生成返回格式未知: {json.dumps(item)[:300]}")

    def _fetch_as_base64(self, url_or_path: str) -> Optional[str]:
        try:
            if url_or_path.startswith("/uploads/"):
                fp = UPLOADS_DIR / url_or_path.split("/")[-1]
                if fp.exists():
                    return base64.b64encode(fp.read_bytes()).decode("ascii")
            if url_or_path.startswith(("http://", "https://")):
                with urllib.request.urlopen(url_or_path, timeout=30) as r:
                    return base64.b64encode(r.read()).decode("ascii")
        except Exception as e:
            print(f"[image_service] fetch base64 failed: {e}")
            return None


# ============================================================
# 即梦多参考 Provider（字节火山引擎，签名复杂，待接入）
# ============================================================
class JimengMultiRefProvider(ImageProvider):
    """即梦多参考生图（字节火山引擎）。需要火山引擎 AccessKey + SecretKey。"""
    name = "jimeng_multiref"
    is_mock = False

    def __init__(self, access_key: str, secret_key: str, model: str = "jimeng-4.0"):
        self.ak = access_key
        self.sk = secret_key
        self.model = model

    def generate_angle_view(self, *args, label: str = "", **kwargs) -> str:
        raise NotImplementedError(
            "即梦多参考生图需要火山引擎签名（HMAC-SHA256 + service=aimage）。"
            "请在 routers/image_service.py 或 services/volcano_service.py 实现签名后启用。"
        )


# ============================================================
# Provider 工厂：根据 settings 选 Provider
# ============================================================
def _load_user_settings() -> dict:
    """从 storage/settings.json 读用户设置（与 routers/settings.py 共用文件）"""
    from app.config import SETTINGS_FILE
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


@dataclass
class _Resolved:
    provider: ImageProvider
    source: str   # "user_config" | "fallback_chat_model" | "fallback_signature_needed" | "fallback_mock"


def get_image_provider() -> _Resolved:
    """根据用户 API 设置决定 Provider：
    - image 组 enabled + api_key + base_url + model 都齐，且 model 是图像模型 → 真实 Provider
    - model 是聊天模型 → Mock（提示用户这不是图像模型）
    - model 是即梦等多参考模型但签名未实现 → Mock（临时演示，等接入签名）
    - 否则降级 MockImageProvider（演示模式）
    """
    cfg = (_load_user_settings().get("image") or {})
    enabled = cfg.get("enabled", False)
    base_url = (cfg.get("base_url") or "").strip()
    api_key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "").strip()

    if not (enabled and base_url and api_key and model):
        return _Resolved(provider=MockImageProvider(), source="fallback_mock")

    det = model_catalog.detect_image(model)
    capability = det.get("capability")

    # 聊天模型不能当图像模型用
    if capability == model_catalog.ImageModelCapability.NOT_IMAGE:
        return _Resolved(provider=MockImageProvider(), source="fallback_chat_model")

    # 即梦多参考需要火山引擎签名，当前未实现，先用 Mock 兜底
    if capability == model_catalog.ImageModelCapability.MULTI_REF and any(k in model.lower() for k in ["jimeng", "即梦"]):
        return _Resolved(provider=MockImageProvider(), source="fallback_signature_needed")

    # 其他图像模型走 OpenAI 兼容接口（如果调用失败，外层会降级 Mock）
    return _Resolved(
        provider=OpenAICompatibleImageProvider(base_url, api_key, model),
        source="user_config",
    )


# 全局实例（每次调用重新解析设置，避免切换 Key 后不生效）
def generate_angle_view(
    front_image_url: Optional[str],
    angle_code: str,
    subject_type: str,
    subject_description: str,
    negative_prompt: str = "",
    label: str = "",
    angle_prompt: str = "",
) -> str:
    """便捷函数：自动选 Provider + 拼 prompt + 返回 URL

    angle_prompt: 外部已生成的完整角度 prompt（优先使用）；为空时内部自动构建。
    真实 Provider 失败时自动降级 Mock，保证流程不中断。
    """
    resolved = get_image_provider()
    if not angle_prompt:
        angle_prompt = build_angle_prompt(subject_type, angle_code, subject_description)
    try:
        return resolved.provider.generate_angle_view(
            front_image_url=front_image_url,
            angle_code=angle_code,
            subject_type=subject_type,
            subject_description=subject_description,
            angle_prompt=angle_prompt,
            negative_prompt=negative_prompt,
            label=label,
        )
    except Exception as e:
        print(f"[image_service] {resolved.provider.name} failed ({resolved.source}): {e}; fallback to Mock")
        return MockImageProvider().generate_angle_view(
            front_image_url=front_image_url,
            angle_code=angle_code,
            subject_type=subject_type,
            subject_description=subject_description,
            angle_prompt=angle_prompt,
            negative_prompt=negative_prompt,
            label=label,
        )


image_service = {
    "generate_angle_view": generate_angle_view,
    "build_angle_prompt": build_angle_prompt,
    "get_provider": get_image_provider,
}
