"""文件上传路由"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from services.storage import storage_service
from app.config import UPLOADS_DIR
from models.schemas import ApiResponse, UploadResponse

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("", response_model=ApiResponse)
async def upload_file(file: UploadFile = File(...)):
    """通用文件上传（图/音频）"""
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20MB
        raise HTTPException(413, "文件超过 20MB")

    info = storage_service.save_upload(content, file.filename)
    return ApiResponse(
        success=True,
        data=UploadResponse(**info),
    )


@router.get("/uploads/{file_id}")
async def get_uploaded_file(file_id: str):
    """下载已上传的文件"""
    path = UPLOADS_DIR / file_id
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path)