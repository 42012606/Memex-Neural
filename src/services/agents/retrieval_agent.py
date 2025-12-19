"""
Retrieval Agent - 检索代理
负责向量检索、BM25 检索、多模态 embedding
"""
import logging
import numpy as np
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload
from src.models.archive import ArchiveRecord
from src.services.file_service import get_file_public_url

logger = logging.getLogger(__name__)


class RetrievalAgent:
    """
    检索代理
    支持向量检索和传统关键词检索
    """
    
    def __init__(self, db: Optional[Session] = None):
        """
        初始化检索代理
        :param db: 数据库会话（可选）
        
        注意：不再需要 VectorServiceFactory，直接使用 AIService.embed_text() 进行向量化
        """
        self.db = db
        # 不再需要 _vector_service，直接使用 AIService
        logger.info("✅ Retrieval Agent 初始化完成（使用 AIService 进行向量化）")
    
    def search_by_keywords(
        self,
        keywords: List[str],
        limit: int = 5,
        user_id: int = 1,
        file_type: Optional[str] = None,
    ) -> List[ArchiveRecord]:
        """
        传统关键词搜索（BM25 风格，使用 SQL LIKE）
        :param keywords: 关键词列表
        :param limit: 返回结果数量
        :param user_id: 用户ID，预留多用户扩展
        :return: 归档记录列表
        """
        if not self.db:
            logger.warning("数据库会话未提供，无法执行关键词搜索")
            return []
        
        try:
            query = self.db.query(ArchiveRecord).filter(
                ArchiveRecord.user_id == user_id  # [预留扩展] 用户隔离
            )
            if file_type:
                query = query.filter(ArchiveRecord.file_type == file_type)
            
            # 构建 OR 条件（任意关键词匹配）
            from sqlalchemy import or_
            conditions = []
            for keyword in keywords:
                conditions.append(ArchiveRecord.filename.like(f"%{keyword}%"))
                conditions.append(ArchiveRecord.summary.like(f"%{keyword}%"))
                conditions.append(ArchiveRecord.category.like(f"%{keyword}%"))
                conditions.append(ArchiveRecord.full_text.like(f"%{keyword}%")) # [Fix] Search in OCR/FullText content
            
            if conditions:
                query = query.filter(or_(*conditions))
            
            results = query.order_by(ArchiveRecord.id.desc()).limit(limit).all()
            logger.info(f"✅ 关键词搜索完成，找到 {len(results)} 条结果")
            return results
        except Exception as e:
            logger.error(f"❌ 关键词搜索失败: {e}")
            return []
    
    
    def search_by_vector(
        self,
        query_text: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        user_id: int = 1,
        min_score: float = 0.45  # [Threshold] Filter out irrelevant results (orthogonal ~0.41)
    ) -> List[Dict[str, Any]]:
        """
        向量相似度搜索 V2 (支持 Parent-Child Indexing)
        
        策略:
        1. 优先搜索 VectorNode (Child Nodes)
        2. 同时搜索 ArchiveRecord (Parent Nodes, 兼容旧数据)
        3. 聚合结果，优先展示最佳 Child Node 的匹配分数
        """
        if not self.db:
            return []
        
        try:
            # 1. 向量化查询
            from src.services.ai_service import AIService
            ai_service = AIService()
            query_vector = ai_service.embed_text(query_text, db_session=self.db)
            
            if not query_vector:
                return []

            # -------------------------------------------------------------------------
            # Query Logic A: Search Child Nodes (finest granularity)
            # -------------------------------------------------------------------------
            from src.models.vector_node import VectorNode
            from pgvector.sqlalchemy import Vector
            import numpy as np

            # Query Child Nodes
            child_query = self.db.query(VectorNode).order_by(
                VectorNode.embedding.l2_distance(query_vector)
            ).limit(top_k * 3) # Fetch more candidate chunks for aggregation
            
            child_results = child_query.all()
            
            # -------------------------------------------------------------------------
            # Query Logic B: Search Parent Archives (legacy/coarse)
            # -------------------------------------------------------------------------
            parent_query = (
                self.db.query(ArchiveRecord)
                .options(selectinload(ArchiveRecord.storage_root))
                .filter(
                    ArchiveRecord.user_id == user_id,
                    ArchiveRecord.embedding.isnot(None),
                    ArchiveRecord.is_vectorized == 1
                )
            )
            # Apply filters
            if filters:
                if "category" in filters:
                    parent_query = parent_query.filter(ArchiveRecord.category == filters["category"])
                if "file_type" in filters:
                    parent_query = parent_query.filter(ArchiveRecord.file_type == filters["file_type"])
            
            parent_results = parent_query.order_by(
                ArchiveRecord.embedding.l2_distance(query_vector)
            ).limit(top_k).all()
            
            logger.info(f"🔍 向量检索: ChildNodes={len(child_results)}, ParentNodes={len(parent_results)}")

            # -------------------------------------------------------------------------
            # Aggregation & Merging
            # -------------------------------------------------------------------------
            aggregated_scores = {} # { archive_id: { "score": float, "snippet": str, "source": str } }
            
            # Helper to calc similarity
            def calc_score(emb):
                if emb is None: return 0.0
                dist = np.linalg.norm(np.array(emb) - np.array(query_vector))
                return 1.0 / (1.0 + dist)

            # Process Child Nodes first
            parent_ids_from_children = set()
            for child in child_results:
                pid = child.parent_archive_id
                score = calc_score(child.embedding)
                
                # Keep the BEST chunk for each parent
                if pid not in aggregated_scores or score > aggregated_scores[pid]["score"]:
                    aggregated_scores[pid] = {
                        "score": score,
                        "snippet": child.content, # Use child content as snippet
                        "source": "child_node",
                        "child_id": child.id
                    }
                    parent_ids_from_children.add(pid)

            # Process Parent Archives (Legacy)
            # Only add if score is better or not present (usually child nodes are better)
            for parent in parent_results:
                pid = parent.id
                score = calc_score(parent.embedding)
                
                if pid not in aggregated_scores:
                    # New find from coarse index
                    aggregated_scores[pid] = {
                        "score": score,
                        "snippet": parent.summary or parent.full_text[:200] if parent.full_text else "",
                        "source": "parent_vector",
                        "child_id": None
                    }
                else:
                    # If parent vector score is surprisingly better than child vector (rare), update it?
                    # Generally we trust Child Node specific match more. 
                    # But let's keep max score.
                    if score > aggregated_scores[pid]["score"]:
                         aggregated_scores[pid]["score"] = score
                         aggregated_scores[pid]["source"] = "parent_vector_boost"

            # -------------------------------------------------------------------------
            # Fetch Archive Details for Final Response
            # -------------------------------------------------------------------------
            all_ids = list(aggregated_scores.keys())
            if not all_ids:
                return []
            
            # Batch fetch needed archives
            # Ensure we fetch all records involved (including those from children only)
            records = self.db.query(ArchiveRecord).options(
                selectinload(ArchiveRecord.storage_root)
            ).filter(ArchiveRecord.id.in_(all_ids)).all()
            
            record_map = {r.id: r for r in records}
            
            final_results = []
            for pid, info in aggregated_scores.items():
                record = record_map.get(pid)
                if not record:
                    continue
                
                # [Threshold Check]
                if info["score"] < min_score:
                    continue
                
                # Apply filters post-aggr (for child nodes results)
                # (Parent query already filtered, but child query didn't check parent filters yet)
                if filters:
                     if "category" in filters and record.category != filters["category"]:
                         continue
                     if "file_type" in filters and record.file_type != filters["file_type"]:
                         continue
                
                # Construct result
                public_url = None
                try:
                    if record.relative_path:
                        public_url = get_file_public_url(record.relative_path)
                except Exception:
                    pass

                final_results.append({
                    "id": str(record.id),
                    "doc_id": str(record.id),
                    "score": float(info["score"]),
                    "metadata": {
                        "filename": record.filename,
                        "category": record.category,
                        "file_type": record.file_type,
                        "path": record.path,
                        "relative_path": record.relative_path,
                        "public_url": public_url,
                        "user_id": record.user_id,
                        # [NEW] Enhanced metadata
                        "matched_content": info["snippet"], 
                        "match_source": info["source"]
                    }
                })
            
            # Sort by score descending
            final_results.sort(key=lambda x: x["score"], reverse=True)
            
            return final_results[:top_k]

        except Exception as e:
            logger.error(f"❌ 向量搜索失败: {e}", exc_info=True)
            return []
    
    def _parse_date(self, value: str) -> Optional[datetime]:
        """宽松解析日期字符串（YYYY-MM-DD / YYYY-MM）。"""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            pass
        try:
            return datetime.fromisoformat(f"{value}-01")
        except Exception:
            return None

    def _match_time_range(self, candidate: Optional[str], time_range: Optional[str], fallback_dt: Optional[datetime]) -> bool:
        """
        使用语义日期优先的时间过滤：
        - candidate: meta_data.semantic_date 或 structured.date
        - fallback_dt: processed_at 等系统时间
        """
        if not time_range:
            return True

        now = datetime.now()
        start = end = None

        tr = time_range.strip()
        import re
        tr = time_range.strip()
        
        # Support lastXd and lastXh generically
        match = re.match(r"^last(\d+)([dh])$", tr)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            if unit == "d":
                # [Fix] Use calendar days (start of day), not rolling 24h
                # last1d = Today + Yesterday (since 00:00 of day before)
                start = (now - timedelta(days=num)).replace(hour=0, minute=0, second=0, microsecond=0)
            elif unit == "h":
                start = now - timedelta(hours=num)
            end = now
        elif "~" in tr:
            parts = tr.split("~", 1)
            start = self._parse_date(parts[0])
            end = self._parse_date(parts[1]) if len(parts) > 1 else None
        else:
            # 单点日期/月份/年份
            start = self._parse_date(tr)
            end = None

        def in_range(dt: datetime) -> bool:
            if start and end:
                return start <= dt <= end
            if start and not end:
                return dt >= start
            return True

        # 优先语义时间
        semantic_dt = self._parse_date(candidate) if candidate else None
        if semantic_dt:
            return in_range(semantic_dt)
        if fallback_dt:
            return in_range(fallback_dt)
        return True

    def hybrid_search(
        self,
        query_text: str,
        keywords: Optional[List[str]] = None,
        top_k: int = 5,
        user_id: int = 1,
        time_range: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        混合搜索（向量 + 关键词）
        :param query_text: 查询文本
        :param keywords: 关键词列表（可选，如果不提供则从 query_text 提取）
        :param top_k: 返回结果数量
        :param user_id: 用户ID，预留多用户扩展
        :return: 搜索结果列表
        """
        # 如果关键词未提供，从查询文本中提取（支持中文）
        if not keywords:
            import re
            # 提取中文关键词（2-4字）
            chinese_words = re.findall(r'[\u4e00-\u9fff]{2,4}', query_text)
            # 提取英文单词（至少3个字符）
            english_words = re.findall(r'\b[a-zA-Z]{3,}\b', query_text)
            # 合并：优先中文关键词，然后英文单词
            keywords = chinese_words[:3] + english_words[:2]
            # 如果还是没有，使用空格分割（适用于英文）或取前10个字符
            if not keywords:
                keywords = query_text.split()[:5] if ' ' in query_text else [query_text[:10]]
        
        # 1. 向量搜索
        vector_filters = {}
        if file_type:
            vector_filters["file_type"] = file_type
        
        # 增强查询文本：如果有关键词，合并到查询文本中以提升搜索精度
        enhanced_query = query_text
        if keywords:
            enhanced_query = f"{query_text} {' '.join(keywords)}"
            logger.debug(f"🔍 增强查询文本: {enhanced_query} (原始: {query_text}, 关键词: {keywords})")
        
        # [Rerank Upgrade] Slightly reduce recall size to improve speed (from 4x to 3x)
        recall_k = top_k * 3 if top_k < 10 else top_k * 2
        vector_results = self.search_by_vector(enhanced_query, top_k=recall_k, user_id=user_id, filters=vector_filters or None)
        
        # 2. 关键词搜索
        keyword_results = self.search_by_keywords(keywords, limit=recall_k, user_id=user_id, file_type=file_type)

        # 2.5 时间过滤（语义日期优先）
        id_set = set()
        for v in vector_results:
            doc_id = v.get("id") or v.get("doc_id")
            if doc_id:
                id_set.add(int(doc_id))
        for k in keyword_results:
            id_set.add(int(k.id))

        records_map = {}
        if self.db and id_set:
            try:
                records = self.db.query(ArchiveRecord).filter(ArchiveRecord.id.in_(list(id_set))).all()
                records_map = {int(r.id): r for r in records}
            except Exception as e:
                logger.warning(f"时间过滤加载记录失败: {e}")

        def pass_time(doc_id: int) -> bool:
            rec = records_map.get(int(doc_id))
            if not rec:
                return True
            meta = rec.meta_data if isinstance(getattr(rec, "meta_data", None), dict) else {}
            sem_date = meta.get("semantic_date") or meta.get("structured", {}).get("date")
            return self._match_time_range(sem_date, time_range, getattr(rec, "processed_at", None))

        vector_results = [r for r in vector_results if pass_time(r.get("id") or r.get("doc_id"))]
        keyword_results = [r for r in keyword_results if pass_time(r.id)]

        # 3. 合并结果（去重，优先向量搜索结果）
        combined = {}
        
        # 获取最大ID (用于判断新旧程度)
        max_id = 0
        if keyword_results:
            max_id = max([r.id for r in keyword_results])
        if vector_results:
            v_max = max([int(r.get("id") or r.get("doc_id") or 0) for r in vector_results])
            max_id = max(max_id, v_max)

        # 先添加向量搜索结果
        for result in vector_results:
            doc_id = result.get("id") or result.get("doc_id")
            if doc_id:
                combined[doc_id] = {
                    "id": doc_id,
                    "score": result.get("score", 0.0),
                    "source": "vector",
                    "metadata": result.get("metadata", {})
                }
        
        # 再添加关键词搜索结果
        for record in keyword_results:
            # [Score Tuning] Lower base score for keyword matches to trust Vector more
            base_score = 0.3  # Was 0.5
            if max_id > 0 and record.id >= max_id - 5:
                 base_score += 0.1 # Was 0.35 - Reduce recency bias to match Vector (~0.45)
            
            # [Fix] Extract snippet from full_text if possible for Reranker context
            snippet = record.summary or ""
            matched_source = "keyword_summary"
            
            if record.full_text and keywords:
                text_lower = record.full_text.lower()
                for kw in keywords:
                    idx = text_lower.find(kw.lower())
                    if idx != -1:
                        # Extract 50 chars before and 150 chars after
                        start = max(0, idx - 50)
                        end = min(len(record.full_text), idx + 150)
                        snippet = record.full_text[start:end]
                        matched_source = "keyword_fulltext_snippet"
                        # Clean up newlines for cleaner context
                        snippet = snippet.replace("\n", " ").strip()
                        break

            if record.id not in combined:
                public_url = None
                try:
                    if record.relative_path:
                        public_url = get_file_public_url(record.relative_path)
                except Exception:
                    pass
                combined[record.id] = {
                    "id": record.id,
                    "score": base_score,  
                    "source": "keyword",
                    "metadata": {
                        "filename": record.filename,
                        "category": record.category,
                        "summary": record.summary,
                        "relative_path": record.relative_path,
                        "public_url": public_url,
                        # [NEW] Inject the snippet for Reranker
                        "matched_content": snippet,
                        "match_source": matched_source
                    }
                }
            else:
                existing_score = combined[record.id]["score"]
                if base_score > existing_score:
                     combined[record.id]["score"] = base_score
                     combined[record.id]["source"] = "keyword_boost"
        
        # -------------------------------------------------------------------------
        # 4. Local Rerank (精排)
        # -------------------------------------------------------------------------
        candidate_items = list(combined.values())
        
        if not candidate_items:
            return []

        # 准备 Rerank 候选文本
        candidate_texts = []
        for item in candidate_items:
            meta = item.get("metadata", {})
            # 优先使用 Child Node 的匹配片段，其次摘要，最后文件名
            text = meta.get("matched_content") or meta.get("summary") or meta.get("filename") or ""
            candidate_texts.append(text)
        
        try:
            from src.services.ai.rerank_provider import RerankService
            reranker = RerankService()
            
            # 执行重排序 (Rerank)
            # 注意: 如果 sentence-transformers 未安装，reranker 会自动回退到原始顺序
            reranked_indices = reranker.rerank(query_text, candidate_texts, top_k=top_k)
            
            # Helper: Sigmoid to normalize logits to 0-1
            def sigmoid(x):
                return 1 / (1 + np.exp(-x))

            final_results = []
            for idx, score in reranked_indices:
                if idx < len(candidate_items):
                    item = candidate_items[idx]
                    
                    # Log raw score for debug
                    norm_score = sigmoid(score)
                    logger.info(f"Rerank Item {item['id']}: Raw={score:.4f}, Norm={norm_score:.4f}, Text={candidate_texts[idx][:50]}...")

                    # Update score to normalized score
                    # 保留原始分数为 original_score
                    if "original_score" not in item:
                        item["original_score"] = item["score"]
                    
                    item["score"] = float(norm_score)
                    item["metadata"]["rerank_score"] = float(norm_score)
                    
                    # [Root Cause Fix] Keyword Verification
                    # If we have explicit keywords, and this doc contains NONE of them, penalize it.
                    # This prevents "Pork Receipt" (no "Electricity") from sneaking in via "Recent" or loose vector match.
                    if keywords:
                        # Check snippets/summary/filename for keyword presence
                        content_to_check = (item.get("metadata", {}).get("matched_content") or "") + \
                                         (item.get("metadata", {}).get("summary") or "") + \
                                         (item.get("metadata", {}).get("filename") or "")
                        
                        # Loose check (case insensitive)
                        has_kw = any(k.lower() in content_to_check.lower() for k in keywords)
                        if not has_kw:
                            # Penalize vague matches.
                            # Exception: If score is SUPER high (>0.85), it might be a synonym we missed (e.g. "Power" vs "Electricity"), so trust it.
                            if float(norm_score) < 0.85:
                                logger.info(f"📉 Penalizing Item {item['id']} (No keyword match): {norm_score:.4f} -> {norm_score * 0.5:.4f}")
                                norm_score = norm_score * 0.5
                                item["score"] = float(norm_score)
                                item["metadata"]["rerank_score"] = float(norm_score)

                    # [Threshold Filtering] Exclude low relevance
                    # With Sigmoid: 0.5 is neutral (logit 0). 0.25 is quite lenient (logit -1.1).
                    if float(norm_score) < 0.40:  # Restored to reasonable 0.40
                         logger.info(f"Skipping Item {item['id']} (Score {norm_score:.4f} < 0.40)")
                         continue 
                    
                    final_results.append(item)
            
            logger.info(f"✅ Rerank 完成，返回 {len(final_results)} 条结果 (TopScore: {final_results[0]['score'] if final_results else 0})")
            return final_results
            
        except ImportError:
            logger.warning("Rerank module import failed, falling back to basic sort.")
        except Exception as e:
            logger.error(f"Rerank process failed: {e}", exc_info=True)
            
        # Fallback: Sort by score descending
        final_results = sorted(combined.values(), key=lambda x: x["score"], reverse=True)[:top_k]
        return final_results
    
    def embed_document(
        self,
        doc_id: str,
        text: str,
        metadata: Dict[str, Any],
        user_id: int = 1
    ) -> bool:
        """
        为文档生成向量并直接写入 PostgreSQL
        :param doc_id: 文档 ID（对应数据库记录 ID）
        :param text: 文档文本内容
        :param metadata: 元数据（filename, category 等，不再使用）
        :param user_id: 用户ID，预留多用户扩展
        :return: 是否成功
        """
        if not self.db:
            logger.warning("数据库会话未提供，无法写入向量")
            return False
        
        try:
            # 1. 调用 Embedding API 生成向量
            from src.services.ai_service import AIService
            ai_service = AIService()
            vector = ai_service.embed_text(text, db_session=self.db)
            
            if not vector:
                logger.warning("⚠️ Embedding API 返回空向量")
                return False
            
            # 2. 直接写入 PostgreSQL 的 embedding 字段
            from datetime import datetime
            record = self.db.query(ArchiveRecord).filter(
                ArchiveRecord.id == int(doc_id),
                ArchiveRecord.user_id == user_id
            ).first()
            
            if not record:
                logger.warning(f"⚠️ 未找到记录: {doc_id}")
                return False
            
            # 更新向量字段
            record.embedding = vector  # pgvector 会自动处理向量类型转换
            record.is_vectorized = 1
            record.vectorized_at = datetime.now()
            
            self.db.commit()
            logger.info(f"✅ 文档向量化成功并写入数据库: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 文档向量化失败: {e}", exc_info=True)
            if self.db:
                self.db.rollback()
            return False
    
    def delete_document_vector(self, doc_id: str) -> bool:
        """从数据库中删除文档向量（清空 embedding 字段）"""
        if not self.db:
            return False
        
        try:
            record = self.db.query(ArchiveRecord).filter(
                ArchiveRecord.id == int(doc_id)
            ).first()
            
            if record:
                record.embedding = None
                record.is_vectorized = 0
                record.vectorized_at = None
                self.db.commit()
                logger.info(f"✅ 文档向量已删除: {doc_id}")
                return True
            else:
                logger.warning(f"⚠️ 未找到记录: {doc_id}")
                return False
        except Exception as e:
            logger.error(f"❌ 删除文档向量失败: {e}")
            if self.db:
                self.db.rollback()
            return False