"""OpenAI GPT-4o 服务封装"""
import json
from typing import Optional
from openai import OpenAI
from app.config import settings


class OpenAIService:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        self.model = settings.openai_model

    def _chat(self, system: str, user: str, response_format: Optional[dict] = None) -> str:
        """统一 chat 调用"""
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        }
        if response_format:
            kwargs["response_format"] = response_format

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content.strip()

    # ============== Step 1：分析角色/产品 ==============

    def analyze_character(self, image_description: str, extra: str = "") -> dict:
        """分析人物档案"""
        system = """你是 AI 视频制作的视觉总监，擅长把人物形象拆成结构化档案，供下游视频生成模型使用。
要求：
1. 描述要极其具体（发型长度、五官比例、肤色色调、服装剪裁），以便 AI 后续生成一致的形象
2. description 字段是一段连贯的中文描述（80-150 字），用于直接注入视频生成的提示词
3. 输出严格 JSON，不要任何多余文字"""

        user = f"""请基于以下人物信息生成一份结构化档案。

【用户原始描述 / 图像特征】
{image_description}

【用户补充说明】
{extra or '无'}

输出 JSON（严格按以下字段）：
{{
  "name": "角色名（用户没指定则填'未命名角色'）",
  "age_range": "年龄段，如 25-30",
  "gender": "性别",
  "ethnicity": "族裔/外貌特征",
  "hair": "发型详细描述（颜色、长度、卷直、刘海）",
  "face_features": "五官描述（眼型、鼻型、唇型、脸型）",
  "body_type": "体型描述",
  "clothing": "服装描述（款式、颜色、材质）",
  "style_tags": ["风格标签1", "风格标签2"],
  "description": "一段连贯的中文描述，用于视频提示词"
}}"""

        text = self._chat(system, user, response_format={"type": "json_object"})
        return json.loads(text)

    def analyze_product(self, image_description: str, extra: str = "") -> dict:
        """分析产品档案"""
        system = """你是 AI 视频制作的产品视觉分析师。任务：把产品外观拆成结构化档案，确保后续视频生成时产品不变形、不变色、不改 logo。
要求：
1. 描述要精确（形状、材质、颜色十六进制、品牌标识位置）
2. description 字段是一段连贯的中文描述（80-150 字）
3. 输出严格 JSON"""

        user = f"""请基于以下产品信息生成结构化档案。

【产品图像特征】
{image_description}

【用户补充说明】
{extra or '无'}

输出 JSON（严格按以下字段）：
{{
  "name": "产品名",
  "category": "产品类别",
  "color": "主色调描述",
  "material": "材质",
  "shape": "形状描述",
  "logo_text": "品牌名/Logo 文字",
  "distinctive_features": "区别性特征（其他产品没有的特征）",
  "description": "一段连贯的中文描述"
}}"""

        text = self._chat(system, user, response_format={"type": "json_object"})
        return json.loads(text)

    def analyze_voice(self, audio_description: str = "") -> dict:
        """分析声音档案（在没有音频元数据时由用户描述推断）"""
        system = """你是 AI 配音的声音分析师，输出 JSON 格式声音档案。"""

        user = f"""基于以下信息分析声音特征：

【音频信息】
{audio_description or '用户上传了一段参考音频，未提供详细描述'}

输出 JSON：
{{
  "gender": "性别",
  "age_range": "年龄段",
  "language": "主要语言（默认 zh）",
  "description": "声音特征描述（音色、音调、语速、情感倾向）"
}}"""

        text = self._chat(system, user, response_format={"type": "json_object"})
        return json.loads(text)

    def generate_character_angles(self, character_desc: str, angle: str) -> str:
        """为人物生成特定角度的图像生成提示词"""
        system = """你是 AI 图像生成提示词专家。根据角色描述和指定角度，输出用于图像生成模型的英文 prompt。
要求：聚焦该角度下的视觉特征，保持与原角色一致。"""

        user = f"""角色描述：{character_desc}

目标角度：{angle}

请输出：
1. 英文 prompt（用于 Flux/SDXL 等模型）
3. 英文 negative prompt（避免变形、变形脸、低质量）

输出 JSON：
{{
  "prompt": "...",
  "negative_prompt": "..."
}}"""
        text = self._chat(system, user, response_format={"type": "json_object"})
        return json.loads(text)

    def generate_product_angles(self, product_desc: str, angle: str) -> str:
        """为产品生成特定角度的图像生成提示词"""
        system = """你是产品图像生成提示词专家。输出英文 prompt，保持产品形状、颜色、Logo 一致。"""

        user = f"""产品描述：{product_desc}

目标角度：{angle}

输出 JSON：
{{
  "prompt": "...",
  "negative_prompt": "..."
}}"""
        text = self._chat(system, user, response_format={"type": "json_object"})
        return json.loads(text)

    def generate_voice_line(self, brief: str, scene_hint: str = "护肤 / 美妆种草") -> str:
        """根据项目创意生成一句配音示范台词
        用于「用户未上传参考音频」时，输出到 TTS 合成以生成默认音色参考音。
        返回一句 12-25 字的中文台词。
        """
        system = """你是 AI 视频文案编剧。任务：根据项目创意输出一句配音示范台词，用于合成 TTS。
要求：
1. 一句话 12-25 字，中文
2. 语气亲切自然，符合种草/带货风格
3. 直接输出台词本身，不带任何标点前缀、不加引号、不换行
"""
        user = f"""【项目创意】{brief or '护肤品日常使用分享'}
【场景类型】{scene_hint}

请输出一句配音台词："""
        return self._chat(system, user).strip().strip('"').strip('「').strip('」').strip()


class MockOpenAIService:
    """无 API key 时使用的演示实现"""

    def __init__(self):
        self.real = OpenAIService()

    def _demo(self, key: str):
        return {
            "analyze_character": {
                "name": "未命名角色",
                "age_range": "25-30",
                "gender": "女",
                "ethnicity": "东亚女性",
                "hair": "中长黑色直发",
                "face_features": "鹅蛋脸、双眼皮、薄唇",
                "body_type": "中等身材",
                "clothing": "米色针织开衫",
                "style_tags": ["自然", "清新"],
                "description": "演示模式生成的默认角色描述——真实模型将基于上传图细分五官与造型。",
            },
            "analyze_product": {
                "name": "演示产品",
                "category": "护肤品",
                "color": "白色 + 玫瑰金",
                "material": "玻璃瓶身",
                "shape": "圆柱形",
                "logo_text": "BRAND",
                "distinctive_features": "玫瑰金金属旋盖",
                "description": "演示模式生成的默认产品描述——真实模型将基于上传图提取形状和 Logo。",
            },
            "analyze_voice": {
                "gender": "女",
                "age_range": "25-30",
                "language": "zh",
                "description": "演示模式生成的默认声音档案。",
            },
        }.get(key, {})

    def analyze_character(self, image_description: str, extra: str = "") -> dict:
        return self._demo("analyze_character")

    def analyze_product(self, image_description: str, extra: str = "") -> dict:
        return self._demo("analyze_product")

    def analyze_voice(self, audio_description: str = "") -> dict:
        return self._demo("analyze_voice")

    def generate_character_angles(self, character_desc: str, angle: str) -> dict:
        return {"prompt": character_desc, "negative_prompt": "ugly, distorted"}

    def generate_product_angles(self, product_desc: str, angle: str) -> dict:
        return {"prompt": product_desc, "negative_prompt": "warped, deformed"}

    def generate_voice_line(self, brief: str, scene_hint: str = "") -> str:
        return "今天给大家种草我自用的这款精华液"


def get_openai_service():
    if settings.openai_api_key and settings.openai_api_key != "xxx":
        return OpenAIService()
    return MockOpenAIService()


# 单例
openai_service = get_openai_service()