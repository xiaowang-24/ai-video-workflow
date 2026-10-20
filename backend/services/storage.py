"""文件存储服务"""
import uuid
import shutil
from pathlib import Path
from typing import Optional
from app.config import UPLOADS_DIR


class StorageService:
    """简单的本地文件存储"""

    def save_upload(self, file_content: bytes, original_filename: str) -> dict:
        """保存上传文件，返回 file_id 和 URL"""
        ext = Path(original_filename).suffix.lower() or ".bin"
        file_id = f"{uuid.uuid4().hex}{ext}"
        dest = UPLOADS_DIR / file_id

        with open(dest, "wb") as f:
            f.write(file_content)

        return {
            "file_id": file_id,
            "filename": original_filename,
            "url": f"/files/uploads/{file_id}",
            "size": len(file_content),
            "local_path": str(dest),
        }

    def get_local_path(self, file_id: str) -> Optional[Path]:
        path = UPLOADS_DIR / file_id
        return path if path.exists() else None

    def delete(self, file_id: str) -> bool:
        path = UPLOADS_DIR / file_id
        if path.exists():
            path.unlink()
            return True
        return False


storage_service = StorageService()