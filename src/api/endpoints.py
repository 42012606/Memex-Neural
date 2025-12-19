import shutil
import logging
import os
from typing import List, Optional
from pathlib import Path
from datetime import datetime

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Depends,
    HTTPException,
    Form,
    BackgroundTasks,
    status,
    Request,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.core.database import get_db, SessionLocal
from src.core.dependencies import get_current_user
from src.core.config import settings
from src.services.processor import FileProcessor
from src.services.ai_service import AIService
from src.models.archive import ArchiveRecord, ProcessingStatus
from src.models.storage import StorageRoot
from src.models.user import User
from src.models.chat import ChatMessage
from src.models.session import ChatSession
from datetime import datetime

# 初始化
router = APIRouter()
logger = logging.getLogger(__name__)

# --- Pydantic Models (API 数据模型) ---

class ArchiveResponse(BaseModel):
    id: int
    filename: str
    category: str
    summary: str
    # [New] V3.1 新增字段
    confidence: Optional[int] = None
    reasoning: Optional[str] = None

class RecentRecord(BaseModel):
    id: int
    filename: str
    category: str
    status: str
    time: str

class LogResponse(BaseModel):
    logs: List[str]

class UploadAcceptedResponse(BaseModel):
    id: int
    status: str


class ArchiveDetailResponse(BaseModel):
    """单条归档查询响应"""

    id: int
    filename: str
    original_filename: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    file_type: str
    processing_status: str
    processing_error: Optional[str] = None
    summary: Optional[str] = None
    full_text: Optional[str] = None
    path: Optional[str] = None  # 兼容字段，返回 relative_path
    storage_root_id: Optional[int] = None
    relative_path: Optional[str] = None
    file_size: Optional[int] = None
    meta_data: Optional[dict] = None
    is_vectorized: Optional[int] = None
    vectorized_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None

# --- Endpoints ---

@router.post("/upload", response_model=UploadAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model_id: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),  # [Persistence]
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    [Core] 上传文件 -> 立即入库 pending -> 背景任务异步处理
    """
    try:
        # [Persistence] Record upload in chat history
        if session_id:
            try:
                # User message: file upload notification
                user_msg = ChatMessage(
                    role="user",
                    content=f"📄 [File Upload] {file.filename}", 
                    model_id="system_upload",
                    session_id=session_id,
                    user_id=current_user_id
                )
                db.add(user_msg)
                db.commit()
                # [NOTE] 完成消息将在归档处理成功/失败后由插件保存
            except Exception as msg_err:
                logger.warning(f"Failed to persist upload message: {msg_err}")

        processor = FileProcessor()
        file_size = 0
        file_type = None
        user = db.query(User).filter(User.id == current_user_id).first()
        username = processor._sanitize_username(user.username if user else f"user_{current_user_id}")
        storage_root = processor._get_default_storage_root(db)

        # 使用存储卷 + 用户名的 INBOX 目录
        inbox_path = Path(storage_root.mount_path) / username / "_INBOX"
        inbox_path.mkdir(parents=True, exist_ok=True)
        temp_path = inbox_path / file.filename

        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = temp_path.stat().st_size if temp_path.exists() else 0
        file_type = processor._get_file_type(temp_path)

        record = ArchiveRecord(
            user_id=current_user_id,
            filename=file.filename,
            original_filename=file.filename,
            file_type=file_type or "Documents",
            category="未分类",
            subcategory="",
            summary="",
            full_text=None,
            storage_root_id=storage_root.id,
            relative_path=str(temp_path.relative_to(storage_root.mount_path).as_posix()),
            file_size=file_size,
            processing_status=ProcessingStatus.PENDING.value,
            processing_error=None,
            processed_at=datetime.now(),
            meta_data={
                "original_filename": file.filename,
                "file_size": file_size,
                "uploaded_at": datetime.utcnow().isoformat(),
                "session_id": session_id,  # [NEW] 用于归档完成后保存聊天记录
            },
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        background_tasks.add_task(
            processor.process_file_background,
            str(temp_path),
            record.id,
            model_id,
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"id": record.id, "status": ProcessingStatus.PENDING.value},
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/archives/{archive_id}", response_model=ArchiveDetailResponse)
async def get_archive_detail(
    archive_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单条归档查询：提供精确处理状态和元数据"""
    try:
        record = (
            db.query(ArchiveRecord)
            .filter(ArchiveRecord.id == archive_id, ArchiveRecord.user_id == current_user_id)
            .first()
        )
        if not record:
            raise HTTPException(status_code=404, detail="Archive not found")

        payload = {
            "id": record.id,
            "filename": record.filename,
            "original_filename": record.original_filename,
            "category": record.category,
            "subcategory": record.subcategory,
            "file_type": record.file_type,
            "processing_status": record.processing_status,
            "processing_error": record.processing_error,
            "summary": record.summary,
            "full_text": record.full_text,
            "path": record.relative_path,  # 兼容旧字段
            "storage_root_id": record.storage_root_id,
            "relative_path": record.relative_path,
            "file_size": record.file_size,
            "meta_data": record.meta_data or {},
            "is_vectorized": record.is_vectorized,
            "vectorized_at": record.vectorized_at,
            "processed_at": record.processed_at,
        }

        status_code = status.HTTP_200_OK
        if record.processing_status in (
            ProcessingStatus.PENDING.value,
            ProcessingStatus.PROCESSING.value,
        ):
            status_code = status.HTTP_202_ACCEPTED

        return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取归档详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取归档详情失败")


@router.get("/archives", response_model=List[ArchiveResponse])
async def get_all_archives(
    skip: int = 0,
    limit: int = 100,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """[Knowledge Base] 获取归档列表"""
    records = (
        db.query(ArchiveRecord)
        .filter(ArchiveRecord.user_id == current_user_id)
        .order_by(ArchiveRecord.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    results = []
    for r in records:
        results.append({
            "id": r.id,
            "filename": r.filename,
            "category": f"{r.category}/{r.subcategory}" if r.subcategory else r.category,
            "summary": r.summary or "无摘要",
            "confidence": 100 if r.processing_status == "completed" else 0, # Placeholder
            "reasoning": r.processing_error
        })
    return results


@router.get("/recents", response_model=List[RecentRecord])
async def get_recent_records(
    limit: int = 10,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """[Utility] 获取最近归档列表"""
    records = (
        db.query(ArchiveRecord)
        .filter(ArchiveRecord.user_id == current_user_id)
        .order_by(ArchiveRecord.id.desc())
        .limit(limit)
        .all()
    )
    results = []
    for r in records:
        results.append({
            "id": r.id,
            "filename": r.filename,
            "category": f"{r.category}/{r.subcategory}",
            "status": "✅ 已归档",
            "time": r.processed_at.strftime("%m-%d %H:%M")
        })







@router.get("/logs", response_model=LogResponse)
async def get_system_logs(lines: int = 50):
    """
    [Utility] 从内存读取实时日志 (避免文件锁阻塞)
    """
    from src.core.log_manager import log_manager
    try:
        # 从内存获取日志
        raw_logs = log_manager.get_logs()
        # 取最后 lines 行
        tail_lines = raw_logs[-lines:] if lines > 0 else raw_logs
        return {"logs": tail_lines}
    except Exception as e:
        return {"logs": [f"❌ 读取内存日志失败: {str(e)}"]}


@router.get("/files/{file_path:path}")
async def serve_file(
    file_path: str,
    request: Request,
    current_user_id: int = Depends(get_current_user)
):
    """
    [File Service] 提供文件访问服务，用于 DashScope API 访问本地文件
    支持音频和图片文件的 HTTP 访问
    """
    try:
        processor = FileProcessor()
        db = SessionLocal()
        try:
            storage_root = processor._get_default_storage_root(db)
            base_dir = Path(storage_root.mount_path)
            full_path = base_dir / file_path
        finally:
            db.close()
        
        # 安全检查：确保文件在用户数据目录内
        try:
            full_path.resolve().relative_to(base_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="文件路径不在允许的目录内")
        
        # 检查文件是否存在
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        
        if not full_path.is_file():
            raise HTTPException(status_code=400, detail="路径不是文件")
        
        # 返回文件，针对部分格式强制正确的 Content-Type
        media_type = "application/octet-stream"
        suffix = full_path.suffix.lower()
        if suffix == ".m4a":
            media_type = "audio/mp4"
        elif suffix == ".mp3":
            media_type = "audio/mpeg"
        elif suffix == ".wav":
            media_type = "audio/wav"
        elif suffix == ".flac":
            media_type = "audio/flac"
        elif suffix == ".ogg":
            media_type = "audio/ogg"

        return FileResponse(
            path=str(full_path),
            filename=full_path.name,
            media_type=media_type
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提供文件访问失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件访问失败: {str(e)}")