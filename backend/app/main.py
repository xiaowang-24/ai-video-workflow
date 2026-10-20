"""FastAPI 主入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import UPLOADS_DIR, ARCHIVES_DIR, FRAMES_DIR, CLIPS_DIR, OUTPUTS_DIR
from routers import upload, archive, projects, settings

app = FastAPI(
    title="AI 视频工作流 API",
    description="生成人物/产品不变形的长视频（人物不换脸 · 产品不变形 · 镜头连贯）",
    version="0.1.0",
)

# CORS（开发期允许所有）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件（提供上传的图片/视频）
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/archives", StaticFiles(directory=str(ARCHIVES_DIR)), name="archives")

# 路由
app.include_router(upload.router)
app.include_router(archive.router)
app.include_router(projects.router)
app.include_router(settings.router)


@app.get("/", include_in_schema=False)
async def root():
    """返回前端单页应用"""
    from fastapi.responses import FileResponse
    static_index = Path(__file__).parent.parent / "static" / "index.html"
    if static_index.exists():
        return FileResponse(static_index, media_type="text/html")
    return {"name": "AI 视频工作流", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    from app.config import settings
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)