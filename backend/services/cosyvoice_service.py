"""阿里云百炼 CosyVoice 3 服务封装
文档：https://help.aliyun.com/zh/model-studio/cosyvoice-quickstart
"""
import os
from typing import Optional
from app.config import settings


class CosyVoiceService:
    def __init__(self):
        self.access_key_id = settings.aliyun_access_key_id
        self.access_key_secret = settings.aliyun_access_key_secret
        self.model = settings.cosyvoice_model

    def extract_voice_embedding(self, audio_path: str) -> str:
        """从参考音频提取说话人音色 ID"""
        # 实际调用阿里百炼 cosyvoice API
        # 文档参考：https://help.aliyun.com/zh/model-studio/developer-reference/cosyvoice-3-api
        raise NotImplementedError(
            "请参考阿里百炼 cosyvoice-300m SDK 文档实现。"
            "SDK: pip install alibabacloud_bailian20231201"
        )

    def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: str,
    ) -> str:
        """用克隆的音色合成语音"""
        raise NotImplementedError("需要配置阿里云凭证后启用")

    def synthesize_default(self, text: str, output_path: str, voice: str = "default") -> str:
        """用系统默认音色（未克隆）合成语音，用于「用户没上传参考音频」的场景。
        真实实现：调用阿里百炼 CosyVoice TTS，使用预设音色（如 longxiaochun/loongstella 等）。
        """
        raise NotImplementedError(
            "请调用阿里百炼 cosyvoice 预设音色 API（voice 参数可填 longxiaochun / loongstella / longyue ...）。"
            "参考文档：https://help.aliyun.com/zh/model-studio/developer-reference/cosyvoice-3-api"
        )


# ============ Mock 实现 ============

class MockCosyVoiceService:
    def __init__(self):
        self.real = CosyVoiceService()

    def extract_voice_embedding(self, audio_path: str) -> str:
        return f"mock_voice_{os.path.basename(audio_path)}"

    def synthesize(self, text: str, voice_id: str, output_path: str) -> str:
        return self._write_wave(text, output_path, tone="mock_clone")

    def synthesize_default(self, text: str, output_path: str, voice: str = "default") -> str:
        return self._write_wave(text, output_path, tone=f"default_{voice}")

    # ---------- 演示模式：本地合成一段示意音频 ----------
    def _write_wave(self, text: str, output_path: str, tone: str = "default") -> str:
        """不依赖任何第三方 TTS，本地用数学函数合成一段 4 秒「带语音节奏」的 WAV
        让用户能在前端播放器听到「滴～ 滴～」的节拍，证明系统真的生成了文件。
        """
        import math
        import struct
        import wave

        sr = 16000
        duration = 4.0
        n = int(sr * duration)

        # 把文本拆成若干"音节"——每个音节用不同的基础频率
        text = (text or "系统合成音色").strip()
        chars_per_seg = max(2, min(6, len(text) // 6 or 3))
        segs = [text[i:i + chars_per_seg] for i in range(0, len(text), chars_per_seg)][:8] or [text]
        n_segs = len(segs)

        # 给每个音节一个稳定的基频 [200, 380]Hz 区段
        base_freqs = []
        for i in range(n_segs):
            if "default" in tone or "default_" in tone:
                base_freqs.append(220 + (i * 23 % 100))   # 女声偏低
            else:
                base_freqs.append(140 + (i * 17 % 80))    # 偏中性

        frames = bytearray()
        for i in range(n):
            seg_idx = min(n_segs - 1, int(i / n * n_segs))
            f0 = base_freqs[seg_idx]
            # 段内包络（一个音节内的音量起伏）
            seg_len = n / n_segs
            local = i % seg_len
            env = math.sin(math.pi * local / seg_len) ** 1.5  # 0→1→0 鼓包
            # 主频 + 两个谐波，模拟类语音的复合波形
            v = env * math.sin(2 * math.pi * f0 * i / sr)
            v += env * 0.4 * math.sin(2 * math.pi * f0 * 1.5 * i / sr)
            v += env * 0.2 * math.sin(2 * math.pi * f0 * 2 * i / sr)
            # 在每段交界处插一点弱噪声，让"音节切换"更明显
            if local < sr * 0.02 or local > seg_len - sr * 0.02:
                v *= 0.3
            sample = max(-32760, min(32760, int(v * 22000)))
            frames += struct.pack("<h", sample)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with wave.open(output_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(bytes(frames))
        return output_path


def get_cosyvoice_service():
    if settings.aliyun_access_key_id and settings.aliyun_access_key_id != "xxx":
        return CosyVoiceService()
    return MockCosyVoiceService()


cosyvoice_service = get_cosyvoice_service()