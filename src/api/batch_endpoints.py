# src/api/batch_endpoints.py
"""
批量导入 API 端点
"""
import logging
import time
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from src.core.database import get_db, SessionLocal
from src.core.dependencies import get_current_user
from src.core.config import settings
from src.services.processor import FileProcessor

router = APIRouter()
logger = logging.getLogger(__name__)

# 全局任务状态（简单实现，生产环境建议用 Redis 或数据库）
batch_tasks = {}


class BatchImportRequest(BaseModel):
    """批量导入请求"""
    file_paths: List[str]  # 文件路径列表（相对路径或绝对路径）
    model_id: Optional[str] = "gemini-2.5-flash"
    rate_limit: Optional[float] = 0.5  # 每个文件处理间隔（秒）


class BatchImportResponse(BaseModel):
    """批量导入响应"""
    task_id: str
    total_files: int
    message: str


class BatchStatusResponse(BaseModel):
    """批量导入状态响应"""
    task_id: str
    status: str  # pending/processing/completed/failed
    total: int
    processed: int
    succeeded: int
    failed: int
    current_file: Optional[str] = None
    errors: List[str] = []


def process_batch_files(
    task_id: str,
    file_paths: List[str],
    model_id: str,
    rate_limit: float,
    user_id: int
):
    """
    后台处理批量文件（在后台任务中执行）
    """
    from src.models.archive import ArchiveRecord, ProcessingStatus
    from datetime import datetime

    task_info = batch_tasks[task_id]
    task_info["status"] = "processing"
    processor = FileProcessor()
    
    succeeded = 0
    failed = 0
    errors = []
    
    # 获取数据库会话用于创建初始记录
    db = SessionLocal()
    
    try:
        for idx, file_path_str in enumerate(file_paths):
            file_path = Path(file_path_str)
            
            # 更新当前处理文件（调度中）
            task_info["current_file"] = file_path.name
            task_info["processed"] = idx + 1
            
            if not file_path.exists():
                failed += 1
                error_msg = f"文件不存在: {file_path}"
                errors.append(error_msg)
                logger.warning(f"⚠️ [{task_id}] {error_msg}")
                continue
            
            try:
                # 1. 准备基础信息
                file_size = file_path.stat().st_size
                file_type = processor._get_file_type(file_path)
                
                # [Dynamic Storage Root Detection]
                #Iterate through all active roots to find the correct parent
                from src.models.storage import StorageRoot
                active_roots = db.query(StorageRoot).filter(StorageRoot.is_active.is_(True)).all()
                
                target_root = None
                relative_path = file_path.name # Default fallback
                
                # Explicitly check relative_to for each root
                for root in active_roots:
                    try:
                        # Resolve paths to ensure consistent comparison
                        root_path = Path(root.mount_path).resolve()
                        target_file_path = file_path.resolve()
                        
                        if target_file_path.is_relative_to(root_path):
                            target_root = root
                            relative_path = str(target_file_path.relative_to(root_path).as_posix())
                            break
                    except Exception:
                        continue
                
                # Fallback to default root if no parent match found (e.g. file outside known roots)
                if not target_root:
                     target_root = next((r for r in active_roots if r.is_default), active_roots[0] if active_roots else None)
                     # Keep relative_path as filename since we can't calculate a real relative path
                
                if not target_root:
                    raise RuntimeError("No active storage roots configured")

                record = ArchiveRecord(
                    user_id=user_id,
                    filename=file_path.name,
                    original_filename=file_path.name,
                    file_type=file_type or "Documents",
                    category="未分类",
                    subcategory="",
                    summary="",
                    full_text=None,
                    storage_root_id=target_root.id,
                    relative_path=relative_path,
                    file_size=file_size,
                    processing_status=ProcessingStatus.PENDING.value,
                    processing_error=None,
                    processed_at=datetime.now(),
                    meta_data={
                        "original_filename": file_path.name,
                        "file_size": file_size,
                        "batch_task_id": task_id,
                        "imported_at": datetime.utcnow().isoformat(),
                    },
                )
                
                db.add(record)
                db.commit()
                db.refresh(record)
                
                # 3. 触发后台处理（发送事件）
                # 3. 触发后台处理（发送事件）
                # process_file_background 负责发射 FILE_UPLOADED 事件
                is_success = processor.process_file_background(
                    str(file_path),
                    record.id,
                    model_id
                )
                
                if is_success:
                    succeeded += 1
                    logger.info(f"✅ [{task_id}] 处理成功: {file_path.name}")
                else:
                    failed += 1
                    err_msg = f"处理失败 (Internal Error): {file_path.name}"
                    errors.append(err_msg)
                    logger.error(f"❌ [{task_id}] {err_msg}")
                
            except Exception as e:
                failed += 1
                error_msg = f"调度失败 {file_path.name}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ [{task_id}] {error_msg}")
                # 尝试回滚
                db.rollback()
            
            # 简单限速，防止瞬间发射过多事件
            if idx < len(file_paths) - 1:
                time.sleep(0.1) 

    finally:
        db.close()
    
    # 更新任务状态
    task_info["status"] = "completed"
    task_info["succeeded"] = succeeded
    task_info["failed"] = failed
    task_info["errors"] = errors
    task_info["current_file"] = None
    logger.info(f"✅ [{task_id}] 批量导入调度完成: 成功 {succeeded}, 失败 {failed}")


@router.post("/batch/import", response_model=BatchImportResponse)
async def batch_import(
    request: BatchImportRequest,
    background_tasks: BackgroundTasks,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量导入文件
    """
    import uuid
    
    # 生成任务 ID
    task_id = str(uuid.uuid4())
    
    # 验证文件路径
    valid_paths = []
    for path_str in request.file_paths:
        path = Path(path_str)
        if path.exists() and path.is_file():
            valid_paths.append(str(path.absolute()))
        else:
            logger.warning(f"文件不存在或不是文件: {path_str}")
    
    if not valid_paths:
        raise HTTPException(status_code=400, detail="没有有效的文件路径")
    
    # 初始化任务状态
    batch_tasks[task_id] = {
        "status": "pending",
        "total": len(valid_paths),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "current_file": None,
        "errors": []
    }
    
    # 添加到后台任务
    background_tasks.add_task(
        process_batch_files,
        task_id,
        valid_paths,
        request.model_id,
        request.rate_limit,
        current_user_id
    )
    
    logger.info(f"📦 批量导入任务已创建: {task_id}, 文件数: {len(valid_paths)}")
    
    return {
        "task_id": task_id,
        "total_files": len(valid_paths),
        "message": f"批量导入任务已创建，共 {len(valid_paths)} 个文件"
    }


@router.get("/batch/status/{task_id}", response_model=BatchStatusResponse)
async def get_batch_status(task_id: str):
    """
    获取批量导入任务状态
    """
    if task_id not in batch_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task_info = batch_tasks[task_id]
    
    return {
        "task_id": task_id,
        "status": task_info["status"],
        "total": task_info["total"],
        "processed": task_info["processed"],
        "succeeded": task_info["succeeded"],
        "failed": task_info["failed"],
        "current_file": task_info.get("current_file"),
        "errors": task_info.get("errors", [])[:10]  # 只返回前10个错误
    }