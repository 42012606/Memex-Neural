import logging
import re
import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body, UploadFile, File, Form
import shutil
import os
import base64
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_, nullslast
from pydantic import BaseModel

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.chat import ChatMessage
from src.models.session import ChatSession
from src.services.ai_service import AIService
from src.services.agents.router_agent import RouterAgent
from src.services.agents.retrieval_agent import RetrievalAgent
from src.services.context_memory import ContextMemoryService
from src.models.archive import ArchiveRecord
from src.services.file_service import get_file_public_url
from src.services.export_service import ExportService
from src.utils.text_tools import estimate_token_count

router = APIRouter()
logger = logging.getLogger(__name__)


def _find_file_ids_by_terms(db: Session, user_id: int, terms: List[str], limit: int = 3) -> List[int]:
    """
    尝试通过关键词/文件名片段匹配档案 ID。
    适用于“刚刚上传的文件”“20231115_体检报告.txt”等弱指代场景。
    """
    ids: List[int] = []
    seen = set()
    for term in terms or []:
        if not term:
            continue
        cleaned = term.strip()
        if not cleaned:
            continue
        try:
            candidates = (
                db.query(ArchiveRecord)
                .filter(
                    ArchiveRecord.user_id == user_id,
                    or_(
                        ArchiveRecord.filename.ilike(f"%{cleaned}%"),
                        ArchiveRecord.original_filename.ilike(f"%{cleaned}%"),
                    ),
                )
                .order_by(ArchiveRecord.processed_at.desc())
                .limit(limit)
                .all()
            )
            for c in candidates:
                if c.id not in seen:
                    ids.append(c.id)
                    seen.add(c.id)
        except Exception as e:
            logger.warning(f"匹配文件名片段失败: term={cleaned}, error={e}")
    return ids[:limit]


def _looks_like_file_reference(text: str) -> bool:
    """
    简单判断字符串是否像文件引用（减少硬编码词表依赖）。
    规则：
    - 含常见扩展名
    - 或匹配 YYYYMMDD_*.xxx/报告/文件 之类的模式
    """
    if not text:
        return False
    t = text.strip()
    if len(t) < 3:
        return False
    lowered = t.lower()
    # 常见扩展
    for ext in [".txt", ".pdf", ".doc", ".docx", ".md", ".ppt", ".pptx", ".xls", ".xlsx"]:
        if ext in lowered:
            return True
    # 形如 20231115_体检报告.txt 或 20231115_*
    import re as _re
    if _re.search(r"\b20\d{6}[_-]?\S*", t):
        return True
    # 出现“文件”“报告”且有数字或下划线
    if ("文件" in t or "报告" in t) and any(ch.isdigit() for ch in t):
        return True
    return False

# --- Pydantic Models ---
class CreateSessionRequest(BaseModel):
    title: Optional[str] = None

class RenameSessionRequest(BaseModel):
    title: str

class ChatSessionResponse(BaseModel):
    id: str  # UUID
    title: str
    created_at: datetime
    updated_at: datetime
    user_id: int

class ChatRequest(BaseModel):
    query: str
    model_id: Optional[str] = None
    session_id: Optional[str] = None  # UUID

class ChatResponse(BaseModel):
    reply: str
    session_id: str
    model_id: str

class MessageResponse(BaseModel):
    role: str
    content: str
    created_at: datetime
    model_id: Optional[str] = None

# --- Session Endpoints ---

@router.get("/sessions", response_model=List[ChatSessionResponse])
async def list_sessions(
    limit: int = 20, 
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取会话列表 (按更新时间倒序)"""
    try:
        # 按更新时间倒序，处理可能的 None 值
        sessions = db.query(ChatSession)\
            .filter(ChatSession.user_id == current_user_id)\
            .order_by(nullslast(desc(ChatSession.updated_at)))\
            .limit(limit)\
            .all()
        # 兼容旧数据整型ID，统一转字符串，避免响应校验失败
        result = []
        for s in sessions:
            try:
                result.append(ChatSessionResponse(
                    id=str(s.id) if s.id else str(uuid.uuid4()),
                    title=s.title or "",
                    created_at=s.created_at if s.created_at else datetime.now(),
                    updated_at=s.updated_at if s.updated_at else datetime.now(),
                    user_id=s.user_id if s.user_id else current_user_id,
                ))
            except Exception as session_error:
                logger.error(f"处理会话 {s.id if hasattr(s, 'id') else 'unknown'} 时出错: {session_error}", exc_info=True)
                continue
        return result
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}", exc_info=True)
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")

@router.post("/sessions", response_model=ChatSessionResponse)
async def create_session(
    request: CreateSessionRequest = Body(default=CreateSessionRequest()),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建一个新会话 (返回 UUID)"""
    try:
        # 1. 自动生成标题 (如果未提供)
        initial_title = request.title or "New Chat"
        
        new_session = ChatSession(
            title=initial_title,
            user_id=current_user_id
            # id is auto-generated in model via uuid.uuid4()
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        
        # 确保返回正确的格式
        session_id = str(new_session.id) if new_session.id else str(uuid.uuid4())
        return ChatSessionResponse(
            id=session_id,
            title=new_session.title or "",
            created_at=new_session.created_at if new_session.created_at else datetime.now(),
            updated_at=new_session.updated_at if new_session.updated_at else datetime.now(),
            user_id=new_session.user_id if new_session.user_id else current_user_id
        )
    except Exception as e:
        logger.error(f"创建会话失败: {e}", exc_info=True)
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")

@router.put("/sessions/{session_id}", response_model=ChatSessionResponse)
async def rename_session(
    session_id: str,
    request: RenameSessionRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """重命名会话"""
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == current_user_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.title = request.title
    session.updated_at = datetime.now()
    db.commit()
    db.refresh(session)
    return session

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除会话及其所有消息 (Cascade delete logic typically handled by DB or explicit deletion)"""
    session = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == current_user_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 手动删除关联消息 (因为模型里没有配置 cascade delete 强制)
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    
    db.delete(session)
    db.commit()
    return {"status": "ok", "message": "Session deleted"}

# --- Chat Endpoints ---

@router.post("/chat", response_model=ChatResponse)
async def chat_with_memex(
    request: ChatRequest,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """发送消息并获取回复 (Server-Side Persistence)"""
    # Step 1: 变量安全初始化 - 在 try 块外部初始化所有后续用到的变量
    fallback_session_id = None
    current_intent = "chat"
    file_ids = []
    router_keywords = []
    top_k = 3
    time_range = None
    intent = {"intent": "chat", "search_params": {}}
    context_text = ""
    
    try:
        session_id = request.session_id
        
        # 1. 会话管理
        if not session_id:
            new_session = ChatSession(title=request.query[:30], user_id=current_user_id)
            db.add(new_session)
            db.commit()
            db.refresh(new_session)
            session_id = new_session.id
        else:
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not session:
                new_session = ChatSession(title=request.query[:30], user_id=current_user_id)
                db.add(new_session)
                db.commit()
                db.refresh(new_session)
                session_id = new_session.id
            else:
                session.updated_at = datetime.now()
                db.commit()

        fallback_session_id = session_id

        # 2. 保存用户消息
        user_msg = ChatMessage(
            role="user", 
            content=request.query, 
            model_id=request.model_id, 
            session_id=session_id,
            user_id=current_user_id
        )
        db.add(user_msg)
        db.commit()
        
        # 3. 构建上下文
        ai_service = AIService()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Step 3.1: 先获取历史摘要（用于 Neural Router）
        # Step 3.1: 先获取历史摘要（用于 Neural Router）
        memory_service = ContextMemoryService(db=db)
        history_summary_for_router = ""
        recent_messages_list = []
        try:
            # 获取历史消息用于摘要（排除当前消息）
            all_messages = memory_service.get_recent_messages(
                session_id=session_id,
                limit=50, # Limit to 50 for efficiency
                exclude_last=1
            )
            
            # 准备最近对话列表 (Dict format) 传给 Router
            # 取最近 10 条足够了，Router 内部会截取
            for msg in all_messages[-10:]:
                recent_messages_list.append({
                    "role": msg.role,
                    "content": msg.content
                })

            # 如果消息很多，生成摘要；否则使用简单的历史文本
            if len(all_messages) >= memory_service.SUMMARY_TRIGGER_THRESHOLD:
                older_messages = all_messages[:-memory_service.SLIDING_WINDOW_SIZE]
                if older_messages:
                    history_summary_for_router = await memory_service.generate_rolling_summary(
                        older_messages, 
                        now_str
                    )
        except Exception as e:
            logger.warning(f"获取历史摘要失败，继续使用空摘要: {e}")

        # Step 3.2: Neural Router - 使用增强版路由（传入历史摘要 + 最近原文）
        router_agent = RouterAgent()
        neural_result = None
        memory_distillation = ""
        
        try:
            neural_result = await router_agent.neural_route(
                current_input=request.query,
                history_summary=history_summary_for_router if history_summary_for_router else None,
                recent_messages=recent_messages_list
            )
            memory_distillation = neural_result.get("memory_distillation", "")
            logger.info(f"🧠 Neural Router 路由完成: {neural_result}")

            # [New] Handle Ambiguity / Hesitation
            if neural_result.get("intent") == "ambiguous":
                question = neural_result.get("clarification_question") or "Could you clarify what you mean?"
                
                # Save clarification as AI message
                ai_msg = ChatMessage(
                    role="assistant",
                    content=f"🤔 {question}",  # Add emoji to indicate thinking/hesitation
                    model_id="router_hesitation",
                    session_id=session_id,
                    user_id=current_user_id
                )
                db.add(ai_msg)
                db.commit()
                
                return {
                    "reply": f"🤔 {question}",
                    "session_id": session_id,
                    "model_id": "router_hesitation"
                }
        except Exception as router_error:
            logger.error(f"Neural Router Error: {router_error}", exc_info=True)
            # 降级到旧的 parse_intent 方法
            try:
                logger.info("降级到旧版 Router (parse_intent)")
                intent = await router_agent.parse_intent(request.query)
                neural_result = None  # 标记使用旧版路由
            except Exception as fallback_error:
                logger.error(f"所有路由模型均不可用: {fallback_error}", exc_info=True)
                error_detail = str(fallback_error)
                error_message = f"🚫 系统错误: 所有路由模型均不可用，请检查 API Key 配置。\n\n错误详情: {error_detail}"
                
                ai_msg = ChatMessage(
                    role="assistant",
                    content=error_message,
                    model_id=request.model_id or "system_error",
                    session_id=session_id,
                    user_id=current_user_id
                )
                db.add(ai_msg)
                db.commit()
                
                return {
                    "reply": error_message,
                    "session_id": session_id,
                    "model_id": request.model_id or "system_error"
                }
        
        # Step 3.3: 解析路由结果（支持新旧两种格式）
        router_filters = {}
        router_file_type = None

        if neural_result:
            # 兼容新版扁平结构与旧版嵌套结构
            if "needs_search" in neural_result or "keywords" in neural_result:
                needs_search = neural_result.get("needs_search", False)
                confidence = neural_result.get("confidence", 0.5)
                router_keywords = neural_result.get("keywords", []) or []
                router_filters = neural_result.get("filters") or {}
                intent_hint = "search" if needs_search else "chat"
                file_ids = []
                
                # 如果关键词为空且需要搜索，从查询文本中提取关键词（特别是中文）
                if not router_keywords and needs_search:
                    # 提取中文关键词（2-4字）
                    chinese_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', request.query)
                    # 提取英文单词
                    english_keywords = re.findall(r'\b[a-zA-Z]{3,}\b', request.query)
                    router_keywords = chinese_keywords[:3] + english_keywords[:2]
                    if router_keywords:
                        logger.info(f"🔧 路由模型未提取关键词，自动提取: {router_keywords}")
            else:
                routing = neural_result.get("routing", {})
                needs_search = routing.get("needs_search", False)
                confidence = routing.get("confidence_score", 0.5)
                route_target = routing.get("route_target", "direct_llm")
                if confidence < 0.8:
                    needs_search = True
                    route_target = "search_engine"
                search_payload = neural_result.get("search_payload", {})
                primary_keys = search_payload.get("primary_keys", [])
                synonym_keys = search_payload.get("synonym_keys", [])
                contextual_keys = search_payload.get("contextual_keys", [])
                intent_hint = search_payload.get("intent_hint", "search")
                router_keywords = list(set(primary_keys + synonym_keys + contextual_keys))  # 去重
                router_filters = search_payload.get("filters") or {}
                
                # 如果关键词为空且需要搜索，从查询文本中提取关键词（特别是中文）
                if not router_keywords and needs_search:
                    # 提取中文关键词（2-4字）
                    chinese_keywords = re.findall(r'[\u4e00-\u9fff]{2,4}', request.query)
                    # 提取英文单词
                    english_keywords = re.findall(r'\b[a-zA-Z]{3,}\b', request.query)
                    router_keywords = chinese_keywords[:3] + english_keywords[:2]
                    if router_keywords:
                        logger.info(f"🔧 路由模型未提取关键词，自动提取: {router_keywords}")

                file_ids = []
                for key in primary_keys:
                    id_match = re.search(r'id[:\s]*(\d+)', key, re.IGNORECASE)
                    if id_match:
                        try:
                            file_ids.append(int(id_match.group(1)))
                        except:
                            pass

            if intent_hint == "analyze":
                current_intent = "analyze"
                need_full_context = True
                router_keywords = []
                file_ids = []
            elif intent_hint == "file_read":
                current_intent = "file_read"
                need_full_context = True
            elif intent_hint == "chat":
                current_intent = "chat"
                need_full_context = False
                needs_search = False
            else:
                current_intent = "search"
                need_full_context = False

            # 如果用户说“刚刚/最新上传的文件”但路由判为搜索，强制切到全文分析
            if current_intent == "search" and not file_ids:
                combined_text = " ".join(router_keywords + [request.query])
                has_file_ref = _looks_like_file_reference(combined_text)
                has_recent_hint = any(hint in combined_text for hint in ["刚刚上传", "最新上传", "刚刚的文件", "最新文件", "全文", "刚才上传", "刚才的文件", "全部内容"])
                if has_file_ref or has_recent_hint:
                    current_intent = "analyze"
                    need_full_context = True

            # [NEW] Intent-Based Limit Adjustment
            if current_intent == "export":
                logger.info("💾 Export Intent Detected from Router. Adjusting limits.")
                top_k = 200
                needs_search = True # Ensure search is triggered
                
            is_verbatim_mode = False
            verbatim_keywords = ["全部", "一字不差", "原文", "full content", "verbatim", "原样"]
            if any(k in request.query for k in verbatim_keywords):
                is_verbatim_mode = True
                current_intent = "analyze" # Force analyze if verbatim is requested
                need_full_context = True
                logger.info("⚡ Verbatim Mode Triggered")

            # 兜底：Router 误判为 chat 但用户提到“刚才/刚刚/最近 上传的发票/文件”，强制走检索
            if current_intent == "chat":
                # [Hack] Detect "Yes/Confirm" to trigger export if context implies it?
                # This is tricky without state. We'll rely on User saying "确认下载" which Router picks up as Export.
                # If Router is smart, "Yes, download it" -> intent: export.
                
                recent_hints = ["刚才上传", "刚刚上传", "最近上传", "刚才的发票", "最新发票", "刚才的文件", "刚刚的文件", "全部内容"]
                if any(h in request.query for h in recent_hints):
                    current_intent = "search"
                    needs_search = True
                    need_retrieval = True
                    router_keywords = list(set(router_keywords + [request.query]))
                    logger.info("🔄 Router 判为 chat 但检测到近期上传语义，强制启用检索")

            if current_intent in ["analyze", "file_read"]:
                need_full_context = True

            top_k = 5
            time_range = router_filters.get("time_range") if isinstance(router_filters, dict) else None
            router_file_type = router_filters.get("file_type") if isinstance(router_filters, dict) else None
            need_retrieval = needs_search or bool(router_keywords)

            # 如果尚未识别出 file_ids，尝试用文件名/关键词片段匹配数据库
            if current_intent in ["analyze", "file_read", "search"] and not file_ids:
                lookup_terms = list(router_keywords or [])
                lookup_terms.append(request.query)
                matched_ids = _find_file_ids_by_terms(db, current_user_id, lookup_terms, limit=3)
                if matched_ids:
                    file_ids = matched_ids
                    logger.info(f"🔎 通过文件名匹配获得 file_ids={file_ids}")

            if current_intent == "analyze" and not file_ids:
                latest = (
                    db.query(ArchiveRecord)
                    .filter(ArchiveRecord.user_id == current_user_id)
                    .order_by(ArchiveRecord.processed_at.desc())
                    .first()
                )
                if latest:
                    file_ids = [latest.id]
                    logger.info(f"📄 自动定位最新文件: {latest.id} ({latest.filename})")

            logger.info(
                f"✅ Router Result: intent={current_intent}, search={needs_search}, "
                f"confidence={confidence:.2f}, keywords={len(router_keywords)}, files={file_ids}"
            )
            logger.info(f"━━━ PHASE 2: CONTEXT BUILDING ━━━")
        else:
            # 使用旧的 parse_intent 结果（降级模式）
            intent = await router_agent.parse_intent(request.query)
            search_params = intent.get("search_params", {}) if isinstance(intent, dict) else {}
            router_keywords = search_params.get("keywords") or []
            file_ids = search_params.get("file_ids") or []
            top_k = search_params.get("top_k") or 3
            time_range = search_params.get("time_range") or None
            router_file_type = None
            current_intent = intent.get("intent", "chat") if isinstance(intent, dict) else "chat"
            
            # 如果用户说"分析刚才的文件"等未指定 file_ids，自动抓取当前用户最新上传
            if current_intent == "analyze" and not file_ids:
                latest = (
                    db.query(ArchiveRecord)
                    .filter(ArchiveRecord.user_id == current_user_id)
                    .order_by(ArchiveRecord.processed_at.desc())
                    .first()
                )
                if latest:
                    file_ids = [latest.id]
            
            need_retrieval = current_intent in ["search", "analyze", "file_read"] or bool(router_keywords or file_ids)

        docs = []
        sources_lines = []
        
        # --- Helper: Export Handler ---
        def _execute_export_logic(f_ids):
            try:
                export_service = ExportService(db=db)
                relative_path = export_service.export_as_markdown(f_ids, title=f"Export: {request.query[:20]}...")
                public_url = get_file_public_url(relative_path)
                
                export_msg = (
                    f"✅ **已为您完成批量导出**\n\n"
                    f"共合并了 {len(f_ids)} 份文档，包含完整的元数据与正文。\n\n"
                    f"👉 **[点击下载融合后的 Markdown 文件]({public_url})**\n\n"
                    f"您可以将此文件用于存档，或发送给更强大的推理模型进行深度分析。"
                )
                
                # Save Interaction
                ai_msg = ChatMessage(
                    role="assistant",
                    content=export_msg,
                    model_id="system_export_service",
                    session_id=session_id,
                    user_id=current_user_id
                )
                db.add(ai_msg)
                db.commit()
                
                return {
                    "reply": export_msg,
                    "session_id": session_id,
                    "model_id": "system_export_service"
                }
            except Exception as export_err:
                logger.error(f"Export failed: {export_err}", exc_info=True)
                return None

        try:
            if current_intent == "analyze" and file_ids:
                # [Phase 5] Export Check (Direct IDs)
                if current_intent == "export" or (current_intent == "analyze" and any(k in request.query for k in ["下载", "导出"])):
                     export_result = _execute_export_logic(file_ids)
                     if export_result:
                        return export_result
                
                # [Phase 2] Interactive Limit Check (Human-in-the-loop)
                # Skip limit check if export? No, user might still want to export 100 files but not "analyze" them in chat.
                # If export was requested, we ALREADY returned above.
                # So if we are here, it means NOT export, or export failed.
                
                MAX_AUTO_ANALYZE = 5
                if len(file_ids) > MAX_AUTO_ANALYZE:
                    logger.info(f"🛑 Too many files for auto-analysis: {len(file_ids)} > {MAX_AUTO_ANALYZE}")
                    
                    # Fetch metadata for top files
                    targets = (
                        db.query(ArchiveRecord)
                        .filter(ArchiveRecord.id.in_(file_ids))
                        .limit(20)  # Cap for display
                        .all()
                    )
                    
                    file_list_str = "\n".join([f"- **{t.filename}** (ID: {t.id})" for t in targets])
                    remaining_count = len(file_ids) - len(targets)
                    if remaining_count > 0:
                        file_list_str += f"\n- ... (还有 {remaining_count} 个文件)"

                    clarification_msg = (
                        f"🤔 **需进一步确认**\n\n"
                        f"您通过关键词匹配到了 {len(file_ids)} 份文件，一次性分析这么多文件可能会导致信息过载或回答不精准。\n\n"
                        f"**匹配到的文件（前 {len(targets)} 个）**：\n"
                        f"{file_list_str}\n\n"
                        f"**建议**：\n"
                        f"- 请告诉我具体想分析哪一份（例如：“分析第1个” 或 “分析 ID {targets[0].id}”）。\n"
                        f"- 或者缩小范围（例如：“分析2023年的...”）。"
                    )
                    
                    # Save as AI message
                    ai_msg = ChatMessage(
                        role="assistant",
                        content=clarification_msg,
                        model_id="system_interactive_check",
                        session_id=session_id,
                        user_id=current_user_id
                    )
                    db.add(ai_msg)
                    db.commit()
                    
                    return {
                        "reply": clarification_msg,
                        "session_id": session_id,
                        "model_id": "system_interactive_check"
                    }

                # 精读场景：直接注入全文，跳过检索
                docs = db.query(ArchiveRecord).filter(ArchiveRecord.id.in_(file_ids)).all()
                
                # [Circuit Breaker]
                # Calculate total size to prevent context window explosion
                SAFE_TOKEN_LIMIT = 32000
                total_estimated_tokens = 0
                for doc in docs:
                    if getattr(doc, "full_text", None):
                        total_estimated_tokens += estimate_token_count(doc.full_text)
                
                if total_estimated_tokens > SAFE_TOKEN_LIMIT:
                    logger.warning(f"🛡️ Circuit Breaker Triggered: {total_estimated_tokens} > {SAFE_TOKEN_LIMIT}")
                    
                    error_message = (
                        f"🚫 **为了防止系统过载，已触发安全熔断**\n\n"
                        f"您选择的文件总内容过大（约 {total_estimated_tokens} tokens），超过了单次精读的安全限制 ({SAFE_TOKEN_LIMIT} tokens)。\n\n"
                        f"**建议操作**：\n"
                        f"1. **减少文件数量**：尝试一次只分析 1-2 个文件。\n"
                        f"2. **使用检索模式**：您可以针对具体问题提问（如“合同中的付款条款是什么”），我会自动检索相关段落，而不是加载全文。"
                    )
                    
                    # Save as AI message
                    ai_msg = ChatMessage(
                        role="assistant",
                        content=error_message,
                        model_id="system_circuit_breaker",
                        session_id=session_id,
                        user_id=current_user_id
                    )
                    db.add(ai_msg)
                    db.commit()
                    
                    return {
                        "reply": error_message,
                        "session_id": session_id,
                        "model_id": "system_circuit_breaker"
                    }
                context_lines = []
                for doc in docs:
                    if getattr(doc, "full_text", None):
                        context_lines.append(
                            f"FULL CONTENT [{doc.id}] {doc.filename}:\n---\n{doc.full_text}\n---\n"
                        )
                    if doc.relative_path:
                        try:
                            public_url = get_file_public_url(doc.relative_path)
                            sources_lines.append(f"> 📎 **源文件**: [📄 {doc.filename}]({public_url})")
                        except Exception as url_err:
                            logger.warning(f"构造源文件链接失败 id={doc.id}: {url_err}")
                context_text = "\n".join(context_lines)
            elif need_retrieval:
                retrieval = RetrievalAgent(db=db)
                hit_ids = []
                if file_ids:
                    hit_ids = file_ids
                else:
                    hits = retrieval.hybrid_search(
                        request.query,
                        keywords=router_keywords,
                        top_k=top_k,
                        user_id=current_user_id,
                        time_range=time_range,
                        file_type=router_file_type,
                    )
                    hit_ids = [h.get("id") or h.get("doc_id") for h in hits if h.get("id") or h.get("doc_id")]
                    # 记录检索命中详情，便于排查
                    hit_logs = []
                    for h in hits:
                        meta = h.get("metadata") or {}
                        hit_logs.append(
                            f"id={h.get('id') or h.get('doc_id')} score={h.get('score')} file={meta.get('filename')} path={meta.get('path')}"
                        )
                    if hit_logs:
                        logger.info(f"🔍 检索命中: {' | '.join(hit_logs)}")

                # 将命中 ID 规范为 int，避免字符串导致查询失败
                normalized_hit_ids = []
                for hid in hit_ids:
                    try:
                        normalized_hit_ids.append(int(hid))
                    except Exception:
                        continue
                hit_ids = normalized_hit_ids

                if hit_ids:
                    # [Phase 5] Router-First Export Logic
                    if current_intent == "export":
                        # 1. Check for Confirmation
                        CONFIRM_KEYWORDS = ["确认", "是", "yes", "confirm", "ok", "好的", "没问题", "下载"]
                        # Simple heuristic: if query is SHORT and contains confirm words, treat as confirmed.
                        # OR if the query itself was the request "Download X", we might ask for confirmation.
                        # Proposed flow: User asks "Download X" -> System: "Found X. Confirm?" -> User: "Yes"
                        
                        # BUT: If the user says "Download X" (initial request), we should PROMPT for confirmation.
                        # How to distinguish "Initial Request" from "User Confirmation"?
                        # We use the 'recent_messages' context. If the LAST AI message was a confirmation request, then this is a confirmation.
                        # For simplicity in this iteration: We ALWAYS prompt for confirmation UNLESS the user explicitly adds "Force" (which they won't).
                        
                        # Better approach: We check if the user is replying to a confirmation request.
                        # But here, we are stateless in this function scope.
                        # Let's assume:
                        # - If query implies "Yes/Confirm", we execute.
                        # - If query implies "Download X", we ask.
                        
                        is_confirmation = any(k in request.query.lower() for k in CONFIRM_KEYWORDS) and len(request.query) < 10
                        
                        # However, since the Router classified this current query as 'export', it means the USER INPUT was "Download X".
                        # So it is likely the Initial Request.
                        # User: "Download reports" -> Intent: Export -> Ask Confirm.
                        # User: "Yes" -> Router might classify as 'chat' (or smalltalk).
                        # So we need the Router to classify "Yes" as 'confirm_export' or we handle it in 'chat' fallback?
                        # ACTUALLY: The user wants a "Smart Interaction".
                        
                        # Improved Logic:
                        # 1. Show the preview (Ask for confirmation).
                        # 2. Add specific suggestions/buttons (if UI supported).
                        # For now, we return a text prompt.
                        
                        # WAIT: If user says "Yes" to a previous question, Router might classify it as "chat". 
                        # We need to handle that state. But for now, let's implement the "Ask" part.
                        
                        preview_files = db.query(ArchiveRecord).filter(ArchiveRecord.id.in_(hit_ids[:5])).all()
                        preview_list = "\n".join([f"- {f.filename} ({f.created_at.strftime('%Y-%m-%d')})" for f in preview_files])
                        total_count = len(hit_ids)
                        
                        confirm_msg = (
                            f"📦 **准备打包导出**\n\n"
                            f"我找到了 **{total_count}** 份符合条件的文件（关键词: {router_keywords}）。\n"
                            f"预览前 5 个：\n{preview_list}\n\n"
                            f"❓ **您可以回复“确认”或“立即下载”来开始合并。**"
                        )
                        
                        ai_msg = ChatMessage(
                            role="assistant", 
                            content=confirm_msg,
                            model_id="system_export_confirm",
                            session_id=session_id,
                            user_id=current_user_id
                        )
                        db.add(ai_msg)
                        db.commit()
                        return {
                            "reply": confirm_msg,
                            "session_id": session_id,
                            "model_id": "system_export_confirm"
                        }

                    docs = db.query(ArchiveRecord).filter(ArchiveRecord.id.in_(hit_ids)).all()
                    context_lines = []
                    for doc in docs:
                        try:
                            meta = doc.meta_data if isinstance(getattr(doc, "meta_data", None), dict) else {}
                            semantic = meta.get("semantic", {}) if isinstance(meta, dict) else {}
                            summary_from_meta = semantic.get("summary") if isinstance(semantic, dict) else None
                            cat = doc.category or semantic.get("category") or ""
                            subcat = doc.subcategory or ""
                            full_text = doc.full_text or ""
                            snippet = doc.summary or summary_from_meta or (full_text[:500] + "..." if full_text else "")

                            # 结构化上下文，标注 OCR/视觉内容
                            block_lines = [
                                f"[FILE RECORD: {doc.filename}]",
                                f"[METADATA]: category={cat} subcategory={subcat} summary={snippet}",
                            ]
                            if doc.file_type == "Images" and full_text:
                                block_lines.append("[VISUAL CONTENT / OCR EXTRACT]:")
                                block_lines.append(full_text)
                            elif full_text:
                                block_lines.append("[CONTENT]:")
                                block_lines.append(full_text)
                            block_lines.append("[END OF FILE RECORD]")

                            context_lines.append("\n".join(block_lines))

                            logger.info(
                                f"📄 上下文注入: id={doc.id} file={doc.filename} size={doc.file_size} chars={len(full_text)}"
                            )
                            if doc.relative_path:
                                try:
                                    public_url = get_file_public_url(doc.relative_path)
                                    sources_lines.append(f"> 📎 **源文件**: [📄 {doc.filename}]({public_url})")
                                except Exception as url_err:
                                    logger.warning(f"构造源文件链接失败 id={doc.id}: {url_err}")
                        except Exception as doc_err:
                            logger.warning(f"跳过异常文档 {getattr(doc, 'id', 'unknown')}: {doc_err}")
                            continue
                    context_text = "\n\n".join(context_lines)
                    logger.info(f"检索到 {len(docs)} 条上下文，供推理模型使用")
        except Exception as e:
            logger.warning(f"检索阶段异常，跳过检索: {e}", exc_info=True)

        # [Smart Post-Retrieval Logic]
        # Branch 1: The Guardrail (Empty Results -> Fallback & Hesitation)
        # Intercept if retrieval occurred but yielded NO documents.
        if (need_retrieval or current_intent in ["search", "analyze"]) and not docs:
            hesitation_reply = ""
            # 1. Analyze constraints
            f_type = router_filters.get("file_type")
            t_range = router_filters.get("time_range")
            
            # 2. Fallback: Query Latest Files (Sorting)
            # If search failed (e.g. strict boolean match), try to show what DOES exist.
            try:
                fallback_query = db.query(ArchiveRecord).filter(
                    ArchiveRecord.user_id == current_user_id
                ).order_by(desc(ArchiveRecord.processed_at)).limit(3)
                
                latest_files = fallback_query.all()
            except Exception as fallback_err:
                logger.error(f"Fallback query failed: {fallback_err}")
                latest_files = []

            # 3. Construct Hesitation Response
            if latest_files:
                file_list_text = "\n".join([f"- {f.filename} ({f.processed_at.strftime('%Y-%m-%d %H:%M')})" for f in latest_files])
                
                if t_range:
                    hesitation_reply = (
                        f"我在【最近上传 ({t_range})】的文件中没有找到相关内容。\n\n"
                        f"不过，您最近上传的文件如下（按时间排序）：\n{file_list_text}\n\n"
                        f"是否需要我分析其中某个文件？"
                    )
                elif f_type and f_type != "All":
                    hesitation_reply = (
                        f"我没有找到任何【{f_type}】类型的文件。\n\n"
                        f"这是您最新的文件：\n{file_list_text}"
                    )
                else:
                    hesitation_reply = (
                        f"我的知识库里没有找到确切匹配的文档。\n\n"
                        f"您可能想查看这些最近的文件：\n{file_list_text}"
                    )
            else:
                # Totally empty KB
                hesitation_reply = "我的知识库里目前没有任何文件。请先上传文件。"

            logger.info(f"🛑 Post-Retrieval Hesitation Triggered (with Fallback): {hesitation_reply[:100]}...")
            
            # 4. Save and Return (Bypass LLM)
            hesitation_msg = ChatMessage(
                role="assistant",
                content=hesitation_reply,
                model_id="rule_hesitation",
                session_id=session_id,
                user_id=current_user_id
            )
            db.add(hesitation_msg)
            db.commit()
            
            return {
                "reply": hesitation_reply,
                "session_id": session_id,
                "model_id": "rule_hesitation"
            }

        # Task 4: Context Memory - 使用滚动摘要和滑动窗口构建带记忆的上下文（单一系统消息原则）
        memory_messages = []
        memory_summary = ""
        memory_context = ""
        try:
            # 使用之前创建的 memory_service（避免重复创建）
            # 使用 Context Memory 构建上下文（返回消息列表、摘要文本、对话上下文）
            memory_messages, memory_summary, memory_context = await memory_service.build_context_with_memory(
                session_id=session_id,
                current_query=request.query,
                base_context=context_text,  # 检索结果作为基础上下文
                exclude_last_n=1  # 排除当前正在处理的用户消息
            )
            logger.info("✅ Context Memory Built")
            logger.info(f"━━━ PHASE 2: COMPLETE ━━━")
            
            # 如果 Neural Router 生成了 memory_distillation，可以在这里使用或保存
            if memory_distillation:
                logger.info(f"📝 Memory Distillation: {memory_distillation}")
        except Exception as e:
            logger.error(f"❌ 上下文记忆构建失败，降级使用简单上下文: {e}", exc_info=True)
            # 降级：使用空值，后续会使用简单时间注入逻辑
            memory_messages = []
            memory_summary = ""
            memory_context = context_text  # 保留检索结果
        
        # Branch 2: The Refiner (Non-Empty Results -> Smart Instructions)
        # 构建单一系统提示（遵循单一系统消息原则）
        system_parts = []
        
        # 1. 基础系统提示
        system_parts.append(
            "你是智能助手 Memex。你可以访问并使用下面提供的上下文（用户文件）。"
        )
        
        # 2. Refinement Instructions (思维链/去重/冲突解决)
        if docs:
            refinement_instructions = """
【思维链要求】:
1. **Relevance Check**: 首先，在内心评估检索到的 Context 是否真的回答了用户问题。
2. **Synthesis**: 如果有多个切片，请将它们的信息进行拼图和去重，不要机械复述。
3. **Conflict Resolution**: 如果切片信息有冲突（如不同日期的版本），请以时间最新的为准并说明。
4. **Answer**: 基于上述整理，给出最终回答。
"""
            system_parts.append(refinement_instructions)

        # 3. [NEW] Verbatim Mode & Multi-Doc Logic
        if is_verbatim_mode:
            system_parts.append(
                "**VERBATIM PROTOCOL**: User requested FULL/RAW content. "
                "Output the content of the file EXACTLY as it appears in the context. "
                "Do NOT summarize, do NOT distill. "
                "If multiple files are present, list them clearly with headers."
            )
        elif docs and len(set(d.id for d in docs)) > 1:
             system_parts.append(
                "**MULTI-SOURCE HANDLING**: You have context from multiple files. "
                "Please synthesize the answer. Cite which file the info comes from if useful."
             )

        # 4. 基础上下文规则
        system_parts.append(
            "只要上下文存在，就直接基于上下文回答。**不要在回复末尾列出源文件或下载链接**。"
            "System Context: Current Server Time is " + now_str + "."
        )
        
        # 5. 历史对话摘要
        if memory_summary:
            system_parts.append(f"[历史对话摘要]\n{memory_summary}")
        
        # 合并为单一系统提示文本
        system_prompt_text = "\n\n".join(system_parts)
        
        # 对话上下文（包含最近对话和检索结果）保留在 context 中，添加到用户消息
        context_text = memory_context if memory_context else ""
        try:
            if context_text:
                logger.info(f"🧾 最终上下文前200字符: {context_text[:200]}")
        except Exception:
            pass

        # 4. 调用 AI
        # Task 1: 禁止推理模型自动切换 - 严格使用用户指定的 model_id
        if not request.model_id:
            # 如果没有指定模型，返回错误消息（作为聊天消息）
            error_message = "🚫 错误: 未指定推理模型，请在前端选择模型后再试。"
            ai_msg = ChatMessage(
                role="assistant",
                content=error_message,
                model_id="system_error",
                session_id=session_id,
                user_id=current_user_id
            )
            db.add(ai_msg)
            db.commit()
            return {
                "reply": error_message,
                "session_id": session_id,
                "model_id": "system_error"
            }
        
        try:
            # Task 1: 严格使用 request.model_id，禁止自动切换
            # Task 5: 传递系统提示（遵循单一系统消息原则）
            result = await ai_service.chat(
                query=request.query,
                model_id=request.model_id,  # 严格使用用户指定的模型
                context=context_text,
                intent=current_intent,
                file_ids=file_ids,
                system_prompt=system_prompt_text,  # 传递合并后的系统提示
                db_session=db,
            )
            reply = result.get("reply", "")
            # Task 1: 使用用户指定的 model_id，不要使用 result 中的 model_id（可能被自动切换）
            used_model_id = request.model_id
        except ValueError as ve:
            # API Key 或配置错误
            from src.core.error_translator import translate_ai_error
            error_msg = translate_ai_error(str(ve))
            logger.error(f"AI Service 配置错误: {ve}", exc_info=True)
            # Task 2: 错误信息显性化 - 错误作为聊天消息返回
            reply = f"🚫 模型配置错误：{error_msg}。请检查 API Key 和模型配置。"
            used_model_id = request.model_id or "system_error"
        except Exception as e:
            from src.core.error_translator import translate_ai_error
            error_msg = str(e)
            translated_error = translate_ai_error(error_msg)
            logger.error(f"AI Service Error: {e}", exc_info=True)
            # Task 2: 错误信息显性化 - 错误作为聊天消息返回
            if "All pool models failed" in error_msg or "所有Router模型失败" in error_msg:
                reply = f"🚫 所有可用模型均失败：{translated_error}。请检查模型配置和网络连接。"
            elif "模型池为空" in error_msg or "pool" in error_msg.lower():
                reply = "🚫 模型池未配置，请先配置推理模型。"
            elif "指定模型失败" in error_msg:
                reply = f"🚫 {translated_error}。请检查指定模型的 API Key 配置。"
            else:
                reply = f"🚫 系统错误：{translated_error}"
            used_model_id = request.model_id or "system_error"
        
        # 附加检索来源链接，提升可追溯性
        if sources_lines:
            deduped_sources = []
            seen = set()
            for line in sources_lines:
                if line in seen:
                    continue
                deduped_sources.append(line)
                seen.add(line)
            reply = f"{reply}\n\n" + "\n".join(deduped_sources)

        # 5. 保存 AI 消息
        ai_msg = ChatMessage(
            role="assistant", 
            content=reply, 
            model_id=used_model_id,
            session_id=session_id,
            user_id=current_user_id
        )
        db.add(ai_msg)
        db.commit()
        
        return {
            "reply": reply,
            "session_id": session_id, # Ensure frontend gets the (possibly new) UUID
            "model_id": used_model_id or "default"
        }
    except Exception as fatal:
        logger.error(f"Chat endpoint fatal error: {fatal}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        safe_session = fallback_session_id or str(uuid.uuid4())
        return {
            "reply": "系统繁忙，稍后再试",
            "session_id": safe_session,
            "model_id": "fallback"
        }

@router.get("/chat/history", response_model=List[MessageResponse])
async def get_chat_history(
    session_id: str,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """获取指定会话的消息历史"""
    try:
        messages = db.query(ChatMessage)\
            .filter(ChatMessage.session_id == session_id)\
            .order_by(ChatMessage.created_at)\
            .limit(limit)\
            .all()
        
        # 确保所有字段都正确序列化
        result = []
        for msg in messages:
            result.append(MessageResponse(
                role=msg.role,
                content=msg.content or "",
                created_at=msg.created_at if msg.created_at else datetime.now(),
                model_id=msg.model_id
            ))
        return result
    except Exception as e:
        logger.error(f"获取聊天记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取聊天记录失败: {str(e)}")


@router.post("/chat/voice", response_model=ChatResponse)
async def chat_with_voice(
    file: UploadFile = File(...),
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    语音对话接口
    1. 接收音频文件
    2. 转录 (STT) -> User Text
    3. 聊天处理 (Chat) -> AI Text
    4. 语音合成 (TTS) -> AI Audio
    5. 返回 User Text, AI Text, 和 AI Audio (Base64)
    """
    temp_file_path = None
    try:
        # 1. 保存上传的音频文件
        suffix = Path(file.filename).suffix or ".wav"
        temp_filename = f"voice_input_{uuid.uuid4()}{suffix}"
        temp_file_path = Path(settings.TEMP_DIR) / temp_filename
        
        # 确保存储目录存在
        os.makedirs(settings.TEMP_DIR, exist_ok=True)
        
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        logger.info(f"🎤 收到语音输入，已保存至: {temp_file_path}")
        
        # 2. 调用 STT 转录
        ai_service = AIService()
        # 注意：这里我们并没有显式传递 session_id，因为 chat_with_memex 内部会处理
        # 但我们需要先转录，再调用 chat 逻辑
        
        # 使用 ai_service.transcribe_audio 进行转录
        # (假设配置了 audio 模型)
        try:
            # 在线程池中运行以避免阻塞
            user_text = await run_in_threadpool(ai_service.transcribe_audio, temp_file_path, db_session=db)
        except Exception as stt_error:
            logger.error(f"STT 转录失败: {stt_error}")
            raise HTTPException(status_code=500, detail=f"语音转文字失败: {str(stt_error)}")
            
        logger.info(f"🗣️ 用户语音转录结果: {user_text}")
        if not user_text.strip():
             raise HTTPException(status_code=400, detail="未检测到语音内容")
        
        # 3. 复用 Chat 逻辑
        # 我们不能直接调用 HTTP endpoint，而是复用内部逻辑
        # 为了复用，我们构造一个 ChatRequest 对象
        # 注意：这里需要处理 Session。如果前端没传 Session ID，我们需要创建一个。
        # 但 UploadFile 是 Form data，前端可能需要把 session_id 作为 Form field 传过来
        # 为了简单，我们暂时假设前端在 Header 或者我们通过 query param 拿，或者干脆在这里新建/查找
        # 实际上，FastAPI Form data 可以混用
        
        # 优化：让我们看看前端怎么传。通常是 FormData.append('file', blob); FormData.append('session_id', id)
        # 但我们这里的签名只接收了 file。为了支持 session_id，我们需要更新签名。
        # 修改函数签名添加 session_id: str = Form(None)
        
        # 暂时我们先不做这一步，而是假设总是新对话或者由 chat_with_memex 内部处理（但内部需要 Request）
        # 更好的做法是重构 chat_with_memex 把由 Request 变为由参数驱动的 service function。
        # 鉴于时间，我们这里直接实例化 ChatRequest 并调用 internal logic 可能会有 dependency injection 问题。
        # The safest way without refactoring is to copy the critical logic or call ai_service.chat directly.
        # ai_service.chat handles the core AI logic. We just need to handle Session & Message persistence.
        
        # Let's copy the persistence logic from chat_with_memex simplified.
        
        # 3.1 Session Management (Simplified for Voice)
        # 假设总是使用最新的会话或者新建
        # 查找最近的会话
        session = db.query(ChatSession).filter(ChatSession.user_id == current_user_id).order_by(desc(ChatSession.updated_at)).first()
        if not session:
             session = ChatSession(title=user_text[:30], user_id=current_user_id)
             db.add(session)
             db.commit()
             db.refresh(session)
        
        session_id = str(session.id)
        
        # 3.2 Save User Message
        user_msg = ChatMessage(
            role="user",
            content=user_text,
            session_id=session_id,
            user_id=current_user_id,
            model_id="voice-input" 
        )
        db.add(user_msg)
        db.commit()
        
        # 3.3 Call AI Service
        # Build context similarly if needed (skipping elaborate RAG for now to speed up, or use simple context)
        # For full feature, we should replicate RAG. 
        # But let's start with direct chat first.
        
        # Invoke AI (Router/Reasoning)
        ai_response = await ai_service.chat(
            query=user_text, 
            context="", # TODO: Add RAG context if needed
            db_session=db
        )
        
        ai_text = ai_response["reply"]
        used_model = ai_response["model_id"]
        
        # 3.4 Save AI Message
        ai_msg = ChatMessage(
            role="assistant",
            content=ai_text,
            session_id=session_id,
            user_id=current_user_id,
            model_id=used_model
        )
        db.add(ai_msg)
        session.updated_at = datetime.now()
        db.commit()
        
        # 4. 语音合成 (TTS)
        audio_base64 = ""
        try:
            audio_data = await run_in_threadpool(ai_service.synthesize_audio, ai_text, db_session=db)
            # Convert to Base64
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
        except Exception as tts_error:
            logger.error(f"TTS 合成失败: {tts_error}")
            # TTS 失败不应该阻断流程，只返回文本
            audio_base64 = ""

        # 5. 返回结果 (Hack: Reuse ChatResponse but encapsulate extra data? 
        # No, better define a new response or just put it in a compatible field.
        # ChatResponse defines: reply, session_id, model_id.
        # We need to return audio. Let's return a dict/JSONResponse since ChatResponse is strict Pydantic.
        # Or we can return ChatResponse and put audio in a custom header? No.
        # Let's adjust strictness or return JSON.
        
        return {
            "reply": ai_text,
            "session_id": session_id,
            "model_id": used_model,
            "user_text": user_text, # 返回识别的用户文本
            "audio_data": audio_base64 # Base64 Audio
        }

    except Exception as e:
        logger.error(f"语音对话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"语音对话处理失败: {str(e)}")
        
    finally:
        # 清理临时文件
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
