# src/services/processor.py

import logging
from pathlib import Path
from typing import Optional
import re
from sqlalchemy.orm import Session
from src.core.database import SessionLocal
from src.services.ai_service import AIService
from src.models.archive import ArchiveRecord, ProcessingStatus
from src.models.storage import StorageRoot
from src.core.config import settings

logger = logging.getLogger(__name__)


class FileProcessor:
    def __init__(self):
        self.ai = AIService()
        # 物理卷根路径基于默认存储卷，具体路径在运行时查询数据库
        self.storage_base = Path(settings.FILE_STORAGE_BASE_PATH)

    def _sanitize_username(self, username: str) -> str:
        """
        清洗用户名防止路径遍历和非法字符，仅保留字母、数字、下划线、连字符和点，连续非法字符替换为下划线。
        """
        if not username:
            return "user"
        safe = re.sub(r"[^\w.-]+", "_", username.strip())
        return safe or "user"

    def _get_default_storage_root(self, db: Session) -> StorageRoot:
        storage = (
            db.query(StorageRoot)
            .filter(StorageRoot.is_active.is_(True), StorageRoot.is_default.is_(True))
            .first()
        )
        if storage:
            return storage
        fallback = db.query(StorageRoot).filter(StorageRoot.is_active.is_(True)).first()
        if fallback:
            return fallback
        raise RuntimeError("No active storage root configured")

    def _get_file_type(self, file_path: Path) -> str:
        """
        根据文件扩展名判断文件类型
        :param file_path: 文件路径
        :return: 文件类型（Documents/Images/Audio/Video/Memos）
        """
        suffix = file_path.suffix.lower()
        
        for file_type, extensions in settings.FILE_TYPE_MAPPING.items():
            if suffix in extensions:
                return file_type
        
        # 默认归类为 Documents
        return "Documents"

    def process_file_background(self, file_path: str, record_id: int, model_id: str = None) -> bool:
        """
        后台任务入口：加载数据库记录并执行处理，结束后更新状态/向量。
        Returns:
            bool: True if event emitted successfully/processing started, False otherwise.
        """
        db = SessionLocal()
        record: Optional[ArchiveRecord] = None
        try:
            record = db.query(ArchiveRecord).filter(ArchiveRecord.id == record_id).first()
            if not record:
                logger.error(f"❌ 未找到记录: id={record_id}")
                return False

            record.processing_status = ProcessingStatus.PROCESSING.value
            record.processing_error = None
            db.commit()

            # [EventBus] 发布文件上传事件
            try:
                import asyncio
                from src.core.events import event_bus, Event
                from src.core.event_types import FILE_UPLOADED
                
                payload = {
                    "file_path": str(file_path),
                    "record_id": record.id,
                    "user_id": record.user_id,
                    "original_filename": record.original_filename or Path(file_path).name,
                    "model_id": model_id
                }
                # 在后台线程中运行异步事件发布
                # 注意：EventBus.publish 内部会等待所有 handler 完成
                # 如果 handler 抛出异常，EventBus 会捕获并打印日志，
                # 但 publish 本身通常不会抛出异常（除非 catastrophic failure）
                asyncio.run(event_bus.publish(Event(FILE_UPLOADED, payload)))
                logger.info(f"⚡ Event emitted: {FILE_UPLOADED} for record {record.id}")
                
                # Check record status again to see if it failed during processing
                db.refresh(record)
                if record.processing_status == ProcessingStatus.FAILED.value:
                    return False
                    
                return True

            except Exception as ev_e:
                logger.error(f"⚠️ Event emission failed: {ev_e}")
                # Update status to failed if event emission strictly failed
                record.processing_status = ProcessingStatus.FAILED.value
                record.processing_error = f"EventBus Error: {str(ev_e)}"
                db.commit()
                return False

        except Exception as e:
            logger.error(f"❌ 后台处理失败: {e}", exc_info=True)
            try:
                if record:
                    record.processing_status = ProcessingStatus.FAILED.value
                    record.processing_error = str(e)
                    db.commit()
            except Exception:
                db.rollback()
            return False
        finally:
            db.close()