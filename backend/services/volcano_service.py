"""火山方舟 AI 服务封装（可灵 Kling + Seedance）
火山方舟文档：https://www.volcengine.com/docs/82379
"""
import os
import re
import uuid
import base64
from pathlib import Path
from typing import Optional, List
from app.config import settings, UPLOADS_DIR


class VolcanoService:
    def __init__(self):
        self.access_key = settings.volcano_access_key
        self.secret_key = settings.volcano_secret_key
        self.api_base = "https://visual.volcengineapi.com"

    def kling_image_generate(
        self,
        prompt: str,
        reference_image_url: Optional[str] = None,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        model: str = "kling-v2",
        **kwargs,
    ) -> str:
        """可灵图像生成（真实实现需火山引擎签名，待配置 AK/SK 后启用）"""
        raise NotImplementedError(
            "需要配置火山引擎 AccessKey/SecretKey 并实现签名后启用。"
        )

    def kling_video_generate(self, *args, **kwargs) -> str:
        raise NotImplementedError("需要配置火山引擎凭证后启用")

    def seedance_video_generate(self, *args, **kwargs) -> str:
        raise NotImplementedError("需要配置火山引擎凭证后启用")


# ============ Mock 实现（开发期使用，无需真实 API key）============
# 策略：对参考图按"角度预设"做差异化变换（旋转/镜像/裁切/缩放/调色），
#       输出 6 张明显不同的 PNG，让用户直观看到多角度生成的形态。
# 真实 API 接入后，此层会被 Kling 真实生成结果替换。

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
    """把 label 转成跨平台安全的文件名片段（替换 Windows 非法字符等）"""
    if not s:
        return "x"
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s).strip().strip(".")
    return re.sub(r"_+", "_", cleaned) or "x"


_ACCENTS = {
    "character": (236, 72, 153),    # pink
    "product": (139, 92, 246),      # purple
    "scene": (14, 165, 233),        # sky
    "costume": (34, 197, 94),       # green
}


# 角度预设：每个角度对应不同的几何变换
_ANGLE_PRESETS = {
    "character": {
        "front":         {"rot": 0,   "scale": 1.00, "crop": None,           "mirror": False, "tint": (1.00, 1.05, 1.00)},
        "three_quarter": {"rot": -18, "scale": 1.00, "crop": None,           "mirror": False, "tint": (1.00, 1.00, 1.00)},
        "profile":       {"rot": -6,  "scale": 1.10, "crop": "left_half",    "mirror": True,  "tint": (0.96, 1.00, 1.05)},
        "full_body":     {"rot": 0,   "scale": 0.55, "crop": None,           "mirror": False, "tint": (1.00, 1.00, 1.00)},
        "half_body":     {"rot": 0,   "scale": 1.20, "crop": "upper_half",   "mirror": False, "tint": (1.03, 1.02, 1.02)},
        "outfit":        {"rot": 0,   "scale": 1.50, "crop": "mid_band",     "mirror": False, "tint": (1.05, 1.00, 0.95)},
    },
    "product": {
        "front":     {"rot": 0,   "scale": 1.00, "crop": None,            "mirror": False, "tint": (1.00, 1.00, 1.00)},
        "side":      {"rot": 90,  "scale": 1.00, "crop": None,            "mirror": False, "tint": (1.00, 1.00, 1.00)},
        "back":      {"rot": 180, "scale": 1.00, "crop": None,            "mirror": False, "tint": (0.98, 0.98, 1.02)},
        "top":       {"rot": 0,   "scale": 1.40, "crop": "upper_third",   "mirror": False, "tint": (1.03, 1.00, 1.00)},
        "45_degree": {"rot": 35,  "scale": 0.95, "crop": None,            "mirror": False, "tint": (1.00, 1.00, 1.00)},
        "logo":      {"rot": 0,   "scale": 1.50, "crop": "center_half",   "mirror": False, "tint": (1.06, 1.06, 1.00)},
    },
    "scene": {
        "establishing": {"rot": 0,  "scale": 1.00, "crop": None,          "mirror": False, "tint": (1.00, 1.00, 1.00)},
        "detail":       {"rot": 0,  "scale": 1.30, "crop": "lower_right", "mirror": False, "tint": (1.00, 1.03, 1.00)},
    },
}


# 800x800 画布的裁切区域
_CROP_REGIONS = {
    "upper_half":  (0,   0,   800, 400),
    "upper_third": (0,   0,   800, 270),
    "left_half":   (0,   80,  400, 720),
    "center_half": (200, 200, 600, 600),
    "mid_band":    (100, 300, 700, 600),
    "lower_right": (400, 400, 800, 800),
}


def _fit_square(img, size: int = 800) -> "Image.Image":
    """按比例缩放到 size 边长，灰色背景居中铺成方形"""
    from PIL import Image
    w, h = img.size
    s = size / max(w, h, 1)
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    img = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (245, 245, 247))
    canvas.paste(img, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def _apply_preset(img, preset: dict):
    """根据预设对 800x800 方形图做几何 + 调色变换"""
    from PIL import Image, ImageOps, ImageEnhance
    if preset.get("mirror"):
        img = ImageOps.mirror(img)
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
    r, g, b = preset.get("tint", (1.0, 1.0, 1.0))
    if r != 1.0:
        img = ImageEnhance.Color(img).enhance(r)
    if g != 1.0:
        img = ImageEnhance.Brightness(img).enhance(g)
    if b != 1.0:
        img = ImageEnhance.Contrast(img).enhance(b)
    return img


def _add_overlay(img, label: str, accent_rgb, is_fallback: bool):
    """叠加彩色边框 + 角度标签 + 演示水印（画在 RGB 上，不依赖 alpha）"""
    from PIL import ImageDraw
    out = img.copy()
    draw = ImageDraw.Draw(out)
    # 边框
    draw.rectangle([(4, 4), (795, 795)], outline=accent_rgb, width=8)
    # 底部黑色蒙版（实色块叠加，视觉等同半透明）
    for y in range(660, 800):
        shade = int(60 * ((y - 660) / 140))
        draw.line([(0, y), (800, y)], fill=(shade, shade, shade))
    # 角度标签
    font_big = _load_font(46)
    font_small = _load_font(20)
    draw.text((32, 690), label, font=font_big, fill=(255, 255, 255))
    if is_fallback:
        draw.text((32, 750), "演示模式 · 真实 API 接入后自动替换", font=font_small, fill=(220, 220, 220))
    else:
        draw.text((32, 750), "基于参考图生成 · 多角度锁定", font=font_small, fill=(220, 220, 220))
    return out


class MockVolcanoService:
    """开发期占位实现：基于参考图做差异化几何变换，输出 6 张明显不同的角度图"""

    def _resolve_local_path(self, reference_image_url: Optional[str]):
        if not reference_image_url:
            return None
        fname = reference_image_url.rstrip("/").split("/")[-1]
        for p in [UPLOADS_DIR / fname, UPLOADS_DIR / fname.lstrip("/")]:
            if p.exists():
                return p
        return None

    def _write_and_return(self, img, subject: str, label: str, fallback: bool) -> str:
        from PIL import Image
        safe = _safe_filename_part(label or "x")
        filename = f"mock_{subject}_{safe}_{uuid.uuid4().hex[:8]}.png"
        out_path = UPLOADS_DIR / filename
        img.save(out_path, "PNG", optimize=False)
        return f"/uploads/{filename}"

    def kling_image_generate(
        self,
        prompt: str = "",
        reference_image_url: Optional[str] = None,
        negative_prompt: str = "",
        label: str = "",
        subject: str = "character",
        angle_code: Optional[str] = None,
        **kwargs,
    ) -> str:
        from PIL import Image

        accent = _ACCENTS.get(subject, _ACCENTS["character"])
        src = self._resolve_local_path(reference_image_url)

        # 无参考图（场景资产等）：输出纯色占位 + 标签
        if src is None:
            canvas = Image.new("RGB", (800, 800), (235, 235, 240))
            return self._write_and_return(canvas, subject, label, fallback=True)

        try:
            src_img = Image.open(src)
            src_img.load()
        except Exception:
            canvas = Image.new("RGB", (800, 800), (235, 235, 240))
            return self._write_and_return(canvas, subject, label, fallback=True)

        base = _fit_square(src_img, 800)
        preset = _ANGLE_PRESETS.get(subject, {}).get(angle_code or "")
        if preset:
            transformed = _apply_preset(base, preset)
        else:
            transformed = base  # 角度码不在预设里，保持原图

        final = _add_overlay(transformed, label or (angle_code or "参考"), accent, is_fallback=False)
        return self._write_and_return(final, subject, label or (angle_code or "angle"), fallback=False)

    def kling_video_generate(self, *args, **kwargs) -> str:
        return "https://www.w3schools.com/html/mov_bbb.mp4"

    def seedance_video_generate(self, *args, **kwargs) -> str:
        return "https://www.w3schools.com/html/mov_bbb.mp4"


def get_volcano_service():
    if settings.volcano_access_key and settings.volcano_access_key != "xxx":
        return VolcanoService()
    return MockVolcanoService()


volcano_service = get_volcano_service()