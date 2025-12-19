
import logging
from src.core.plugins import BasePlugin, EventBus
from src.core.event_types import ARCHIVE_COMPLETED, VECTORIZATION_COMPLETED
from src.core.events import Event
from src.services.ai_service import AIService
from src.core.database import SessionLocal
from src.models.archive import ArchiveRecord
from datetime import datetime

logger = logging.getLogger(__name__)

class CoreVectorizerPlugin(BasePlugin):
    """
    核心向量化插件
    职责:
    1. 监听 ARCHIVE_COMPLETED
    2. 获取 full_text 或 summary
    3. 调用 AI Embedding
    4. 更新数据库
    """
    
    def __init__(self):
        self.ai = AIService()

    @property
    def name(self) -> str:
        return "CoreVectorizerPlugin"

    def register(self, bus: EventBus):
        bus.subscribe(ARCHIVE_COMPLETED, self.handle_archive_completed)
        logger.info("✅ 核心向量化插件(CoreVectorizerPlugin)已注册，正在监听 ARCHIVE_COMPLETED 事件")

    async def handle_archive_completed(self, event: Event):
        archive_id = event.payload.get("archive_id")
        logger.info(f"🧩 [向量化插件] 准备向量化归档 ID: {archive_id}")
        
        # 实际逻辑待 CoreArchiverPlugin 启用并发射事件后才会触发
        await self._process_vectorization(archive_id)

    async def _process_vectorization(self, archive_id: int):
        db = SessionLocal()
        try:
            record = db.query(ArchiveRecord).filter(ArchiveRecord.id == archive_id).first()
            if not record:
                return
            
            # [Core Upgrade] 获取要向量化的文本
            # [Phase 3] Metadata Injection: Inject Title/Type/Tags into text
            tags_data = record.meta_data.get("tags", []) if isinstance(record.meta_data, dict) else []
            if isinstance(tags_data, str): 
                tags_list = [tags_data]
            elif isinstance(tags_data, list):
                tags_list = [str(t) for t in tags_data]
            else:
                tags_list = []

            meta_header = (
                f"Title: {record.filename}\n"
                f"Type: {record.file_type}\n"
                f"Category: {record.category or 'Uncategorized'}\n"
                f"Tags: {', '.join(tags_list)}\n"
                f"Summary: {record.summary or 'N/A'}\n"
                f"---\n"
            )

            # 优先使用 full_text (图片ocr/文档内容)，其次 summary，最后 filename
            body_content = record.full_text or record.summary or record.filename or ""
            text_to_embed = meta_header + body_content

            if not text_to_embed.strip():
                logger.warning(f"⚠️ 归档 {archive_id} 没有可用于向量化的文本")
                return

            logger.info(f"🧩 [向量化插件] 开始处理归档 {archive_id}，长度: {len(text_to_embed)} 字符")
            
            # -------------------------------------------------------------------------
            # 1. 传统的粗粒度向量 (Coarse-grained Vector) - 保持兼容性
            # 将对应整个 Archive 的向量存入 archives 表
            # -------------------------------------------------------------------------
            import asyncio
            
            # 如果文本太长，截断用于主向量 (防止 token 溢出，DashScope 一般限制 2048-8000 tokens)
            # 这里取前 2000 字符作为"主摘要"
            coarse_text = text_to_embed[:2000] 
            
            vector = await asyncio.to_thread(self.ai.embed_text, coarse_text)
            if vector:
                record.embedding = vector 
                record.is_vectorized = 1
                record.vectorized_at = datetime.now()
                logger.info(f"  Existing archive vector updated.")

            # -------------------------------------------------------------------------
            # 2. 细粒度切片 (Fine-grained Chunking) - Parent-Child Indexing
            # 将文本切分为多个 Child Nodes，存入 vector_nodes 表
            # -------------------------------------------------------------------------
            from src.models.vector_node import VectorNode
            
            # 清理旧的 vector nodes (防止重复)
            # db.query(VectorNode).filter(VectorNode.parent_archive_id == archive_id).delete()
            # 暂时不删除，假设是新增或覆盖。如果需要幂等性，应该先删后加。
            # 为了安全起见，先检查是否已存在
            existing_count = db.query(VectorNode).filter(VectorNode.parent_archive_id == archive_id).count()
            if existing_count > 0:
                 logger.info(f"  Cleaning up {existing_count} existing vector nodes...")
                 db.query(VectorNode).filter(VectorNode.parent_archive_id == archive_id).delete()

            # 切片参数
            CHUNK_SIZE = 2000  # [Optimization] Increased from 500 to 2000 to avoid over-chunking
            OVERLAP = 200     # 上下文重叠
            
            chunks = []
            if len(text_to_embed) > CHUNK_SIZE:
                 start = 0
                 while start < len(text_to_embed):
                     end = min(start + CHUNK_SIZE, len(text_to_embed))
                     # 尝试在标点符号处断开 (简单的 split 优化)
                     # if end < len(text)... find last newline or punctuation...
                     # 暂且简单切分
                     chunk_text = text_to_embed[start:end]
                     chunks.append(chunk_text)
                     start += (CHUNK_SIZE - OVERLAP)
            else:
                 chunks.append(text_to_embed)
            
            logger.info(f"  Generated {len(chunks)} chunks. Starting batch embedding...")

            # 批量或循环生成向量
            # 目前 AIService.embed_text 是单条的，我们循环调用
            # (未来可以优化为 batch 接口)
            
            created_nodes = 0
            for i, chunk in enumerate(chunks):
                # 跳过太短的碎片
                if len(chunk.strip()) < 10:
                    continue
                
                # 为每个 chunk 生成向量
                chunk_vector = await asyncio.to_thread(self.ai.embed_text, chunk)
                
                if chunk_vector:
                    node = VectorNode(
                        parent_archive_id=archive_id,
                        content=chunk,
                        chunk_index=i,
                        embedding=chunk_vector,
                        meta={"source_length": len(text_to_embed), "is_image_desc": record.file_type == "image"}
                    )
                    db.add(node)
                    created_nodes += 1
            
            db.commit()
            logger.info(f"✅ [向量化插件] 归档 {archive_id} 完成: 主向量 + {created_nodes} 个 Child Nodes")

        except Exception as e:
            logger.error(f"❌ 向量化失败: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()
