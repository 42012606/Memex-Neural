
import logging
import shutil
import re
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session
from src.core.database import SessionLocal
from src.core.plugins import BasePlugin, EventBus
from src.core.event_types import FILE_UPLOADED, ARCHIVE_COMPLETED
from src.core.events import Event
from src.services.ai_service import AIService
from src.models.archive import ArchiveRecord, ProcessingStatus, FileType
from src.models.storage import StorageRoot
from src.models.user import User
from src.models.chat import ChatMessage
from src.core.config import settings
from src.core.config_manager import ConfigManager

logger = logging.getLogger(__name__)

class CoreArchiverPlugin(BasePlugin):
    """
    核心归档插件
    职责:
    1. 监听 FILE_UPLOADED
    2. 执行 AI 分析 (OCR/ASR 集成在此处，或是调用 helper)
    3. 语义重命名 & 移动文件
    4. 更新数据库
    5. 发布 ARCHIVE_COMPLETED
    """
    
    def __init__(self):
        self.ai = AIService()

    @property
    def name(self) -> str:
        return "CoreArchiverPlugin"

    def register(self, bus: EventBus):
        self.bus = bus  # Save bus reference
        bus.subscribe(FILE_UPLOADED, self.handle_file_uploaded)
        logger.info("✅ 核心归档插件(CoreArchiverPlugin)已注册，正在监听 FILE_UPLOADED 事件")

    async def handle_file_uploaded(self, event: Event):
        # 启用插件执行逻辑
        enable_execution = True 
        
        file_path_str = event.payload.get("file_path")
        record_id = event.payload.get("record_id")
        
        logger.info(f"🧩 [归档插件] 收到任务: {file_path_str}")
        
        if not enable_execution:
            logger.info("⏸️ [归档插件] 影子模式启用中，跳过实际处理。")
            return

        # 这里的逻辑是从 processor.py 移植过来的，改为异步/事件驱动风格
        await self._process_archive_flow(file_path_str, record_id, event.payload.get("model_id"))

    async def _process_archive_flow(self, file_path_str: str, record_id: int, model_id: str = None):
        """实际处理流程"""
        file_path = Path(file_path_str)
        db: Session = SessionLocal()
        try:
            record = db.query(ArchiveRecord).filter(ArchiveRecord.id == record_id).first()
            if not record:
                logger.error(f"❌ 未找到归档记录: {record_id}")
                return

            # Update status
            record.processing_status = ProcessingStatus.PROCESSING.value
            db.commit()

            # 复用 core_archiver 内部的方法执行处理
            # 注意：由于这是异步方法，但调用的 AI/DB 操作大部分是同步的，
            # 在高并发下可能需要 run_in_executor，但目前保持简单移植
            record = await self._process_and_persist(file_path, db, model_id=model_id, record=record)
            
            # 最后发射完成事件
            payload = {
                "record_id": record.id,
                "file_path": str(file_path), # 注意：文件可能已经被移动，这里应该是 record.relative_path 或新的绝对路径
                "status": "COMPLETED"
            }
            # await self.bus.publish(Event(ARCHIVE_COMPLETED, payload))

        except Exception as e:
            logger.error(f"❌ 归档插件处理失败: {e}", exc_info=True)
        finally:
            db.close()

    # --- 以下是从 processor.py 移植并适配的方法 ---

    def _sanitize_username(self, username: str) -> str:
        if not username:
            return "user"
        safe = re.sub(r"[^\w.-]+", "_", username.strip())
        return safe or "user"

    def _get_default_storage_root(self, db: Session) -> StorageRoot:
        # 1. 优先查找设为默认的存储库
        default_root = db.query(StorageRoot).filter(
            StorageRoot.is_default == True, 
            StorageRoot.is_active == True
        ).first()
        if default_root:
            return default_root

        # 2. 如果没有默认，查找任意一个活动的存储库
        any_active = db.query(StorageRoot).filter(StorageRoot.is_active == True).first()
        if any_active:
            return any_active

        # 3. 如果没有任何存储库，自动创建一个指向 data/archives 的默认本地存储库
        # (这通常会在 main.py 启动时发生，但作为防守性编程保留在此)
        logger.warning("⚠️ 未找到有效存储库，正在创建默认本地存储库...")
        fallback_path = settings.FILE_STORAGE_BASE_PATH
        
        # 检查是否已存在同路径但未激活的
        existing = db.query(StorageRoot).filter(StorageRoot.mount_path == str(fallback_path)).first()
        if existing:
            existing.is_active = True
            existing.is_default = True
            db.commit()
            return existing

        new_default = StorageRoot(
            name="Default_Local",
            mount_path=str(fallback_path),
            is_active=True,
            is_default=True
        )
        db.add(new_default)
        db.commit()
        db.refresh(new_default)
        return new_default

    def _merge_meta(self, *meta_parts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for part in meta_parts:
            if isinstance(part, dict):
                merged.update(part)
        return merged

    def _pick_year_month(self, date_str: Optional[str], fallback_dt: datetime) -> (str, str):
        try:
            if date_str:
                dt = datetime.fromisoformat(date_str)
                return dt.strftime("%Y"), dt.strftime("%m")
        except Exception:
            pass
        return fallback_dt.strftime("%Y"), fallback_dt.strftime("%m")
    
    def _get_file_type(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        for file_type, extensions in settings.FILE_TYPE_MAPPING.items():
            if suffix in extensions:
                return file_type
        return "Documents"
    
    def _file_type_dir(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix in [".pdf", ".txt", ".doc", ".docx", ".md", ".csv"]:
            return "Documents"
        if suffix in [".jpg", ".jpeg", ".png", ".heic", ".gif", ".bmp", ".webp", ".svg"]:
            return "Images"
        if suffix in [".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg"]:
            return "Audio"
        if suffix in [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm"]:
            return "Video"
        return "Others"

    def _normalize_filename(self, suggested_name: str, date_str: str) -> str:
        # 提取扩展名
        path_obj = Path(suggested_name)
        suffix = path_obj.suffix
        stem = path_obj.stem
        
        # 检查文件名是否已经包含日期前缀
        date_patterns = [
            r'^\d{8}_',           # YYYYMMDD_
            r'^\d{4}[-_]\d{2}[-_]\d{2}[-_]',  # YYYY-MM-DD- 或 YYYY_MM_DD_
        ]
        
        for pattern in date_patterns:
            if re.match(pattern, stem):
                return suggested_name
        
        # 如果文件名不包含日期前缀，添加日期前缀
        today = datetime.now()
        date_part = today.strftime("%Y-%m-%d")
        return f"{date_part}-{stem}{suffix}"

    def _generate_target_path(
        self,
        suggested_name: str,
        year: str,
        month: str,
        file_type_dir: str,
        username: str,
        storage_root: StorageRoot,
    ) -> (Path, str, int):
        safe_type = file_type_dir or "Others"
        year_month = f"{year}.{month}"
        relative_dir = Path(username) / year_month / safe_type
        target_dir = Path(storage_root.mount_path) / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        final_name = self._normalize_filename(suggested_name, f"{year}-{month}")
        final_path = target_dir / final_name

        counter = 1
        while final_path.exists():
            stem = Path(final_name).stem
            suffix = Path(final_name).suffix
            final_path = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        relative_path = str((relative_dir / final_path.name).as_posix())
        return final_path, relative_path, storage_root.id

    def _handle_failed_file(self, file_path: Path, file_type_dir: str, year_month: str, error_msg: str, storage_root: StorageRoot, username: str):
        failed_dir = Path(storage_root.mount_path) / username / year_month / file_type_dir / "_FAILED"
        failed_dir.mkdir(parents=True, exist_ok=True)
        
        failed_path = failed_dir / file_path.name
        if file_path.exists():
            shutil.move(str(file_path), str(failed_path))
            logger.warning(f"⚠️ 文件处理失败，已移动到: {failed_path}")
            logger.warning(f"   错误信息: {error_msg}")

    # --- API Wrappers ---
    
    def _call_vision_api(self, file_path: Path, db: Optional[Session] = None) -> Optional[str]:
        try:
            logger.info(f"📸 [Plugin] 调用 Vision API: {file_path.name}")
            text = self.ai.recognize_image(str(file_path), db_session=db)
            if text:
                logger.info(f"✅ OCR 识别成功，文本长度: {len(text)}")
                return text
            return None
        except Exception as e:
            logger.warning(f"⚠️ OCR 识别失败: {e}")
            return None
    
    def _call_audio_api(self, file_path: Path, db: Optional[Session] = None) -> Optional[str]:
        try:
            logger.info(f"🎵 [Plugin] 调用 Audio API 转录: {file_path.name}")
            text = self.ai.transcribe_audio(file_path, db_session=db)
            if text:
                logger.info(f"✅ 音频转录成功，文本长度: {len(text)}")
                return text
            return None
        except Exception as e:
            logger.error(f"❌ 音频转录失败: {e}")
            return None
    
    def _call_embedding_api(self, text: str, db: Optional[Session] = None) -> Optional[list]:
        try:
            if not text or not text.strip():
                return None
            vector = self.ai.embed_text(text.strip(), db_session=db)
            if vector:
                return vector
            return None
        except Exception as e:
            logger.warning(f"⚠️ 向量化失败: {e}")
            return None

    def _extract_text_from_file(self, file_path: Path, file_type: str, db: Optional[Session] = None) -> Optional[str]:
        logger.info(f"📄 [Plugin] 提取文本: {file_path.name} ({file_type})")
        try:
            if file_type == "Images":
                return self._call_vision_api(file_path, db=db)
            elif file_type == "Audio":
                return self._call_audio_api(file_path, db=db)
            elif file_type == "Documents":
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read(50000)
                        return text if text.strip() else None
                except Exception:
                    return None
            return None
        except Exception as e:
            logger.error(f"❌ 提取文本异常: {e}")
            return None

    async def _process_and_persist(self, file_path: Path, db: Session, model_id: str = None, record: Optional[ArchiveRecord] = None) -> ArchiveRecord:
        """核心处理逻辑 (从 processor.py 移植)"""
        logger.info(f"🔄 [Plugin] Processing: {file_path.name}")

        user_id = getattr(record, "user_id", settings.USER_ID)
        username = None
        storage_root: Optional[StorageRoot] = None
        year_month = None

        try:
            user = db.query(User).filter(User.id == user_id).first()
            username = self._sanitize_username(user.username if user else f"user_{user_id}")
            storage_root = self._get_default_storage_root(db)

            file_type = self._get_file_type(file_path)
            file_type_dir = self._file_type_dir(file_path)
            today = datetime.now()
            
            extracted_text = self._extract_text_from_file(file_path, file_type, db=db)
            
            analysis = {}
            try:
                analysis = self.ai.analyze_file(
                    file_path,
                    model_id=model_id,
                    context_text=extracted_text,
                    db_session=db
                ) or {}
                import json
                if isinstance(analysis, dict):
                    logger.info(f"🔍 [Plugin] Analysis: {json.dumps(analysis, ensure_ascii=False)}")
            except Exception as e:
                logger.error(f"❌ [Plugin] Analysis Failed: {e}")
                analysis = {"error": "analysis_failed", "error_detail": str(e)}

            semantic = analysis.get("semantic", {}) if isinstance(analysis, dict) else {}
            structured = analysis.get("structured", {}) if isinstance(analysis, dict) else {}

            # 语义重命名逻辑
            ai_suggested_filename = analysis.get("suggested_filename", "") if isinstance(analysis, dict) else ""
            if analysis.get("error") == "analysis_failed":
                suggested_name = file_path.name
            else:
                if ai_suggested_filename and ai_suggested_filename.strip():
                    suggested_name = ai_suggested_filename.strip()
                    suggested_name = re.sub(r'[<>:"/\\|?*]', '_', suggested_name)
                    suggested_name = suggested_name.strip(' .')
                    if not suggested_name:
                        suggested_name = file_path.name
                else:
                    suggested_name = file_path.name

            year, month = self._pick_year_month(structured.get("date"), today)
            year_month = f"{year}.{month}"
            category = semantic.get("category") or "Unsorted"

            final_path, relative_path, storage_root_id = self._generate_target_path(
                suggested_name, year, month, file_type_dir, username, storage_root
            )

            # 移动文件
            shutil.move(str(file_path), str(final_path))
            logger.info(f"📂 [Plugin] Moved to: {final_path}")

            # 再次读取文本 (如果之前没读到或需要修正)
            full_text = extracted_text
            if not full_text and file_type == "Documents":
                try:
                    with open(final_path, "r", encoding="utf-8", errors="ignore") as f:
                        full_text = f.read(50000)
                except Exception:
                    pass

            file_size = final_path.stat().st_size

            merged_meta = self._merge_meta(
                getattr(record, "meta_data", None),
                {
                    "original_filename": getattr(record, "original_filename", file_path.name),
                    "suggested_filename": suggested_name,
                    "file_size": file_size,
                    "processed_at": today.isoformat(),
                    "processing_source": "CoreArchiverPlugin" # 标记来源
                },
                analysis if isinstance(analysis, dict) else None,
            )
            semantic_date = structured.get("date") or merged_meta.get("semantic_date")
            if semantic_date:
                merged_meta["semantic_date"] = semantic_date

            if record:
                record.filename = final_path.name
                record.file_type = file_type or "Documents"
                record.category = category
                record.subcategory = ""
                record.summary = semantic.get("summary") or ""
                record.full_text = full_text
                record.storage_root_id = storage_root_id
                record.relative_path = relative_path
                record.file_size = file_size
                record.processing_status = ProcessingStatus.COMPLETED.value
                record.processing_error = None
                record.processed_at = today
                record.meta_data = merged_meta

            db.commit()
            db.refresh(record)

            # 向量化 - 移除，转交给 CoreVectorizerPlugin
            # vector_text = full_text or record.summary or record.filename
            # if vector_text:
            #     vector = self._call_embedding_api(vector_text, db=db)
            #     if vector:
            #         record.embedding = vector
            #         record.is_vectorized = 1
            #         record.vectorized_at = datetime.now()
            #         db.commit()

            # 最后发射完成事件
            payload = {
                "archive_id": record.id, # Changed key to match CoreVectorizerPlugin expectation
                "file_path": str(file_path),
                "status": "COMPLETED"
            }
            # Temporarily use run_in_executor or just await since we are in async
            await self.bus.publish(Event(ARCHIVE_COMPLETED, payload))
            logger.info(f"✅ [CoreArchiverPlugin] Emitted ARCHIVE_COMPLETED for {record.id}")

            # [NEW] 保存成功消息到聊天记录
            session_id = merged_meta.get("session_id")
            if session_id:
                try:
                    tags = semantic.get("tags", [])
                    tags_str = " ".join([f"#{t}" for t in tags]) if tags else ""
                    success_msg = ChatMessage(
                        role="assistant",
                        content=f"✅ **{category}** | {record.filename}\n{semantic.get('summary', '')}\n{tags_str}".strip(),
                        model_id="system_archiver",
                        session_id=session_id,
                        user_id=user_id
                    )
                    db.add(success_msg)
                    db.commit()
                except Exception as chat_err:
                    logger.warning(f"Failed to save completion message: {chat_err}")

            return record

        except Exception as e:
            logger.error(f"❌ [Plugin] Process Failed: {e}", exc_info=True)
            if db:
                db.rollback()
            
            # 失败处理：移动到 _FAILED
            if file_path.exists():
                try:
                    file_type_dir = self._file_type_dir(file_path)
                    fallback_year_month = year_month or datetime.now().strftime("%Y.%m")
                    if storage_root and username:
                        self._handle_failed_file(file_path, file_type_dir, fallback_year_month, str(e), storage_root, username)
                except Exception:
                    pass

            if record:
                record.processing_status = ProcessingStatus.FAILED.value
                record.processing_error = str(e)
                db.commit()
                
                # [NEW] 保存失败消息到聊天记录
                session_id = record.meta_data.get("session_id") if record.meta_data else None
                if session_id:
                    try:
                        fail_msg = ChatMessage(
                            role="assistant",
                            content=f"❌ 归档失败: {record.original_filename}\n错误: {str(e)[:100]}",
                            model_id="system_archiver",
                            session_id=session_id,
                            user_id=record.user_id
                        )
                        db.add(fail_msg)
                        db.commit()
                    except Exception:
                        pass
            
            raise e

