"""应用配置（从 .env 加载）"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # 火山引擎
    volcano_access_key: str = ""
    volcano_secret_key: str = ""
    kling_model_name: str = "kling-v3"
    seedance_model_name: str = "seedance-1.5-pro"

    # 阿里云百炼
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    cosyvoice_model: str = "cosyvoice-300m"

    # 应用
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    storage_root: str = "../storage"
    max_upload_size_mb: int = 20


settings = Settings()

# 存储路径
STORAGE_ROOT = Path(__file__).parent.parent / settings.storage_root.lstrip("./")
UPLOADS_DIR = STORAGE_ROOT / "uploads"
ARCHIVES_DIR = STORAGE_ROOT / "archives"
FRAMES_DIR = STORAGE_ROOT / "frames"
CLIPS_DIR = STORAGE_ROOT / "clips"
OUTPUTS_DIR = STORAGE_ROOT / "outputs"
PROJECTS_DIR = STORAGE_ROOT / "projects"
SETTINGS_FILE = STORAGE_ROOT / "settings.json"

for d in [STORAGE_ROOT, UPLOADS_DIR, ARCHIVES_DIR, FRAMES_DIR, CLIPS_DIR, OUTPUTS_DIR, PROJECTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)