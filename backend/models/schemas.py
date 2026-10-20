"""数据模型 / Schema"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ============ 通用 ============

class ApiResponse(BaseModel):
    success: bool = True
    message: str = ""
    data: Optional[Any] = None


class UploadResponse(BaseModel):
    success: bool = True
    file_id: str
    filename: str
    url: str
    size: int


# ============ Step 1：档案卡 ============

class ArchiveCardCreate(BaseModel):
    """创建档案卡的请求"""
    character_image_id: Optional[str] = None      # 人物参考图 file_id
    product_image_id: Optional[str] = None        # 产品参考图 file_id
    audio_id: Optional[str] = None                # 参考音频 file_id
    extra_description: Optional[str] = None       # 用户额外描述


class CharacterCard(BaseModel):
    """人物档案卡"""
    name: str = "未命名角色"
    age_range: str = ""
    gender: str = ""
    ethnicity: str = ""
    hair: str = ""                  # 发型描述
    face_features: str = ""         # 五官描述
    body_type: str = ""
    clothing: str = ""
    style_tags: List[str] = []
    description: str = ""           # 完整段落描述（用于提示词注入）
    reference_images: List[str] = []   # file_id 列表


class ProductCard(BaseModel):
    """产品档案卡"""
    name: str = "未命名产品"
    category: str = ""
    color: str = ""
    material: str = ""
    shape: str = ""
    logo_text: str = ""
    distinctive_features: str = ""
    description: str = ""
    reference_images: List[str] = []


class VoiceCard(BaseModel):
    """声音档案卡"""
    reference_audio_id: Optional[str] = None
    speaker_id: Optional[str] = None        # CosyVoice 提取的 speaker embedding ID
    gender: str = ""
    age_range: str = ""
    language: str = "zh"
    description: str = ""


class ArchiveCard(BaseModel):
    """完整档案卡（人物+产品+声音）"""
    id: str
    character: CharacterCard
    product: ProductCard
    voice: VoiceCard
    created_at: datetime
    updated_at: datetime
    status: str = "draft"     # draft / confirmed