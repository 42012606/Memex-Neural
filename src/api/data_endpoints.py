# src/api/data_endpoints.py
"""
数据管理 API 端点
"""
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from src.core.database import get_db, SessionLocal
from src.core.dependencies import get_current_user
from src.core.config import settings
from src.models.archive import ArchiveRecord
from src.models.storage import StorageRoot
from src.models.vector_node import VectorNode

router = APIRouter()
logger = logging.getLogger(__name__)

# 批量向量化任务状态（简单内存存储，生产环境应使用 Redis 等）
_batch_vectorize_tasks: Dict[str, Dict[str, Any]] = {}


@router.delete("/data/clear")
async def clear_all_data(
    confirm: bool = False,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    清空所有数据（文件和数据库）
    ⚠️ 危险操作：需要二次确认
    
    :param confirm: 必须为 True 才能执行
    :param db: 数据库会话
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="此操作需要二次确认，请设置 confirm=true"
        )
    
    from src.models.chat import ChatMessage
    from src.models.session import ChatSession
    
    try:
        # 1. 清空当前用户的 Chat 历史 (Message -> Session)
        # 注意：先删除 Message，再删除 Session，避免外键约束（如果未设置级联）
        # 这里为了安全起见，查询该用户的所有 Session ID
        user_sessions = db.query(ChatSession.id).filter(ChatSession.user_id == current_user_id).all()
        session_ids = [s.id for s in user_sessions]
        
        if session_ids:
            deleted_msgs = db.query(ChatMessage).filter(ChatMessage.session_id.in_(session_ids)).delete(synchronize_session=False)
            deleted_sessions = db.query(ChatSession).filter(ChatSession.id.in_(session_ids)).delete(synchronize_session=False)
            logger.info(f"✅ 已删除 {deleted_msgs} 条消息和 {deleted_sessions} 个会话（用户 {current_user_id}）")
        else:
            deleted_msgs = 0
            deleted_sessions = 0
        
        db.commit()
        print(f"Deleted {deleted_sessions} sessions.")

        # 2.0 Clear Vector Nodes (Dependencies)
        print("Clearing Vector Nodes...")
        deleted_vectors = db.query(VectorNode).filter(VectorNode.user_id == current_user_id).delete(synchronize_session=False)
        db.commit()
        print(f"Deleted {deleted_vectors} vector nodes.")

        # 2. Clear Archives (Knowledge Base)
        deleted_records = db.query(ArchiveRecord).filter(ArchiveRecord.user_id == current_user_id).delete(synchronize_session=False)
        
        db.commit()
        logger.info(f"✅ 已删除 {deleted_records} 条归档记录")
        
        # 3. 清空当前用户的物理文件
        user_data_dir = Path(settings.DATA_DIR) / "users" / str(current_user_id)
        deleted_files = 0
        deleted_dirs = []
        
        if user_data_dir.exists():
            # 仅保留 logs 目录以便调试，其他全部删除（包括 _INBOX, _NEEDS_REVIEW）
            preserve_dirs = {"logs"}
            
            for item in user_data_dir.iterdir():
                if item.name in preserve_dirs:
                    continue
                
                try:
                    if item.is_file():
                        item.unlink()
                        deleted_files += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                        deleted_dirs.append(item.name)
                except Exception as e:
                    logger.warning(f"Failed to cleanup {item}: {e}")
            
            logger.info(f"✅ 已删除 {deleted_files} 个文件和 {len(deleted_dirs)} 个目录（用户 {current_user_id}）")
        
        return {
            "status": "ok",
            "message": f"清空完成: {deleted_records} 归档, {deleted_sessions} 会话, {deleted_msgs} 消息, {deleted_files} 文件",
            "deleted_dirs": deleted_dirs,
            "note": "⚠️ 数据已完全重置 (Chat History & Files Cleared)"
        }
    except Exception as e:
        logger.error(f"❌ 清空数据失败: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"清空数据失败: {str(e)}")


def _process_batch_vectorize(task_id: str, record_ids: List[int], user_id: int):
    """
    后台任务：批量向量化
    """
    from src.core.database import SessionLocal
    from src.services.agents.retrieval_agent import RetrievalAgent
    from datetime import datetime
    
    db = SessionLocal()
    try:
        _batch_vectorize_tasks[task_id]["status"] = "processing"
        _batch_vectorize_tasks[task_id]["started_at"] = datetime.now().isoformat()
        
        retrieval = RetrievalAgent(db=db)
        total = len(record_ids)
        success_count = 0
        failed_count = 0
        
        for idx, record_id in enumerate(record_ids):
            try:
                record = db.query(ArchiveRecord).filter(
                    ArchiveRecord.id == record_id,
                    ArchiveRecord.user_id == user_id
                ).first()
                
                if not record:
                    failed_count += 1
                    continue
                
                # 如果已经向量化，跳过（1=已向量化）
                if record.is_vectorized == 1:
                    success_count += 1
                    continue
                
                # 构建向量化所需的文本和元数据
                vector_text = record.full_text or record.summary or record.filename
                if not vector_text:
                    failed_count += 1
                    continue
                
                metadata = {
                    "filename": record.filename,
                    "category": record.category,
                    "subcategory": record.subcategory or "",
                    "file_type": record.file_type,
                    "path": record.relative_path
                }
                
                # 调用向量化
                vectorized = retrieval.embed_document(
                    doc_id=str(record.id),
                    text=vector_text,
                    metadata=metadata,
                    user_id=record.user_id
                )
                
                if vectorized:
                    record.is_vectorized = 1  # Integer 类型：1=已向量化
                    record.vectorized_at = datetime.now()
                    db.commit()
                    success_count += 1
                else:
                    failed_count += 1
                
                # 更新进度
                _batch_vectorize_tasks[task_id]["progress"] = idx + 1
                _batch_vectorize_tasks[task_id]["success_count"] = success_count
                _batch_vectorize_tasks[task_id]["failed_count"] = failed_count
                
            except Exception as e:
                logger.error(f"向量化记录 {record_id} 失败: {e}")
                failed_count += 1
                _batch_vectorize_tasks[task_id]["failed_count"] = failed_count
        
        _batch_vectorize_tasks[task_id]["status"] = "completed"
        _batch_vectorize_tasks[task_id]["completed_at"] = datetime.now().isoformat()
        _batch_vectorize_tasks[task_id]["total"] = total
        _batch_vectorize_tasks[task_id]["success_count"] = success_count
        _batch_vectorize_tasks[task_id]["failed_count"] = failed_count
        
        logger.info(f"✅ 批量向量化完成: 成功 {success_count}, 失败 {failed_count}")
    except Exception as e:
        logger.error(f"❌ 批量向量化任务失败: {e}", exc_info=True)
        _batch_vectorize_tasks[task_id]["status"] = "failed"
        _batch_vectorize_tasks[task_id]["error"] = str(e)
    finally:
        db.close()


@router.post("/data/vectorize/batch")
async def batch_vectorize(
    background_tasks: BackgroundTasks,
    all_files: bool = False,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    批量向量化文件
    :param all_files: 是否向量化所有未向量化的文件
    :param user_id: 用户ID
    """
    import uuid
    from datetime import datetime
    
    try:
        # 查询需要向量化的记录
        query = db.query(ArchiveRecord).filter(
            ArchiveRecord.user_id == current_user_id
        )
        
        if not all_files:
            # 只向量化未向量化的文件（0=未向量化，NULL=未向量化）
            query = query.filter(
                (ArchiveRecord.is_vectorized == 0) | (ArchiveRecord.is_vectorized.is_(None))
            )
        
        records = query.all()
        
        if not records:
            return {
                "status": "ok",
                "message": "没有需要向量化的文件",
                "task_id": None
            }
        
        # 创建任务
        task_id = str(uuid.uuid4())
        record_ids = [r.id for r in records]
        
        _batch_vectorize_tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "total": len(record_ids),
            "progress": 0,
            "success_count": 0,
            "failed_count": 0,
            "created_at": datetime.now().isoformat()
        }
        
        # 提交后台任务
        background_tasks.add_task(_process_batch_vectorize, task_id, record_ids, current_user_id)
        
        return {
            "status": "ok",
            "message": f"已创建批量向量化任务，共 {len(record_ids)} 个文件",
            "task_id": task_id,
            "total": len(record_ids)
        }
    except Exception as e:
        logger.error(f"创建批量向量化任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/data/vectorize/status/{task_id}")
async def get_vectorize_status(task_id: str):
    """
    获取批量向量化任务状态
    """
    if task_id not in _batch_vectorize_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return _batch_vectorize_tasks[task_id]


@router.delete("/archives/{archive_id}")
async def delete_archive(
    archive_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    删除单个归档记录及其物理文件
    """
    # 1. 查询记录
    archive = db.query(ArchiveRecord).filter(
        ArchiveRecord.id == archive_id,
        ArchiveRecord.user_id == current_user_id
    ).first()
    
    if not archive:
        raise HTTPException(status_code=404, detail="Archive not found")

    # 2. 删除物理文件
    # 使用 model 中定义的 path 属性获取绝对路径
    file_path = archive.path
    if file_path:
        try:
            path_obj = Path(file_path)
            if path_obj.exists():
                if path_obj.is_file():
                    path_obj.unlink()
                elif path_obj.is_dir():
                    shutil.rmtree(file_path)
                logger.info(f"Deleted physical file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete physical file {file_path}: {e}")
            # 不阻断数据库删除，但记录错误

    # 2.5. 删除关联的 Vector Nodes (避免外键约束冲突)
    db.query(VectorNode).filter(VectorNode.parent_archive_id == archive_id).delete()

    # 3. 删除数据库记录
    db.delete(archive)
    db.commit()
    
    return {"status": "success", "message": f"Archive {archive_id} deleted"}