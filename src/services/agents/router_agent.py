"""
Router Agent - 意图路由器
负责识别用户意图，输出结构化 JSON 控制下游流程
"""
import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional, List

from pydantic import BaseModel, Field, ValidationError

from src.services.ai_service import AIService
from src.core.prompt_manager import prompt_manager
from src.core.config_manager import config_manager

logger = logging.getLogger(__name__)


class RouterDecision(BaseModel):
    """Router 3.0 decision block."""

    intent: str = Field(default="chat", description="Primary intent: 'search', 'chat', or 'export'")
    needs_search: bool = Field(default=False)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_clarification: bool = Field(default=False, description="If confidence < 0.7, set True")
    clarification_question: Optional[str] = Field(default=None, description="Question to ask user if ambiguous")


# 语义时间描述 -> 后端过滤器映射
TIME_HINT_MAP = {
    "非常近期": "last1h",
    "近期": "last7d",
    "今天": "last1d",
    "本周": "last7d",
    "本月": "last30d",
    "上个月": "last60d",
}

# 语义文件类型 -> 后端类型映射
FILE_TYPE_MAP = {
    "图片": "Images",
    "照片": "Images",
    "截图": "Images",
    "文档": "Documents",
    "PDF": "Documents",
    "文本": "Documents",
    "音频": "Audio",
    "录音": "Audio",
    "语音": "Audio",
    "视频": "Video",
}


class RouterFilters(BaseModel):
    """Router 3.0 filters (converted from semantic hints)."""

    file_type: Optional[str] = Field(default=None, description="Images|Documents|Audio|Video")
    time_range: Optional[str] = Field(default=None, description="e.g., last7d/2023-11")


class RouterSearchPayload(BaseModel):
    """Router 3.0 search payload with semantic hints."""

    keywords: List[str] = Field(default_factory=list)
    # New semantic hint fields (直接从LLM获取)
    time_hint: Optional[str] = Field(default=None, description="语义时间描述如'非常近期'、'近期'、'今天'")
    file_type_hint: Optional[str] = Field(default=None, description="语义文件类型如'图片'、'文档'")
    # Legacy filter field (为兼容性保留，由 time_hint/file_type_hint 自动转换)
    filters: RouterFilters = Field(default_factory=RouterFilters)


class RouterResponse(BaseModel):
    """Structured response schema for Router 3.0."""

    thought_process: str = Field(default="", description="Brief internal reasoning, < 50 words")
    router: RouterDecision = Field(default_factory=RouterDecision)
    search_payload: RouterSearchPayload = Field(default_factory=RouterSearchPayload)
    memory_distillation: str = Field(default="")





class RouterAgent:
    """
    Router 2.1：小模型 JSON 路由
    - 使用配置中的 router 模型（通过 AIService 动态读取）
    - 输出结构化意图，驱动检索/全量读取/闲聊
    - 多维关键词提取 + 即时记忆蒸馏
    """

    def __init__(self):
        self.ai_service = AIService(service_type="router")

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """从模型输出中提取 JSON，容忍代码块与前后噪声"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```\w*\n", "", cleaned)
            cleaned = re.sub(r"\n```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]
        try:
            return json.loads(cleaned)
        except Exception:
            logger.warning(f"Router JSON 解析失败，返回原文: {cleaned}")
            return {}

    def _parse_response(self, response_content) -> RouterResponse:
        """
        Helper: Parse response from LLM into Pydantic model.
        Handles:
        1. DashScope/AI Service Wrappers ({'reply': ...})
        2. JSON Strings (with/without markdown)
        3. Raw Dictionaries
        """
        try:
            # 1. UNWRAP: Handle DashScope wrapper {'reply': '...'}
            if isinstance(response_content, dict) and "reply" in response_content:
                response_content = response_content["reply"]

            # 2. STRING PARSING: Handle JSON strings
            if isinstance(response_content, str):
                clean_content = response_content.strip()
                # Remove Markdown code blocks
                if "```json" in clean_content:
                    clean_content = clean_content.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_content:
                    clean_content = clean_content.split("```")[1].split("```")[0].strip()

                data = json.loads(clean_content)
                return RouterResponse(**data)

            # 3. DICT PARSING: Handle direct data dicts
            if isinstance(response_content, dict):
                return RouterResponse(**response_content)

            # Case 4: Unknown Type
            logger.warning(f"⚠️ Router received unknown type: {type(response_content)}")
            raise ValueError(f"Unknown response type: {type(response_content)}")

        except Exception as e:
            logger.error(f"❌ Router Parsing Failed. Error: {e}")
            # Internal Fallback to prevent crash inside parser
            return RouterResponse(
                thought_process=f"Parse Error: {e}",
                router=RouterDecision(needs_search=True, confidence=0.5),
                search_payload=RouterSearchPayload(keywords=[]),
                memory_distillation="",
            )

    async def parse_intent(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        解析用户意图，输出统一 JSON：
        {
          "intent": "search|file_read|chat|analyze|smalltalk",
          "need_full_context": bool,
          "search_params": {
            "keywords": [],
            "file_ids": [],
            "time_range": "",
            "top_k": 3
          }
        }
        """
        # Task 3: 上下文时间注入
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        schema_template = prompt_manager.get("system.router_schema", default="")
        if not schema_template:
            # Fallback if DB is empty and no default provided (though we seeded it)
            logger.warning("Empty system.router_schema! Using minimal fallback.")
            schema_template = """You are a Router. Output JSON: {"intent": "chat"}"""
            
        schema_prompt = schema_template.replace("{{current_time}}", current_time).replace("{{query}}", query)

        # 不再捕获异常，直接向上抛出（Task 2: 严谨报错机制）
        response = await self.ai_service.chat(query="请返回上面 Schema 的 JSON。", context=schema_prompt)
        response_text = response.get("reply", "") if isinstance(response, dict) else str(response)
        parsed = self._parse_json(response_text) or {}
        
        # 如果解析失败，抛出异常而不是返回默认值
        if not parsed:
            raise ValueError("Router 模型返回的 JSON 解析失败，无法识别用户意图")

        # 填充默认值，避免下游 KeyError
        intent = parsed.get("intent", "chat") or "chat"
        need_full_context = bool(parsed.get("need_full_context", False))
        search_params = parsed.get("search_params") or {}
        keywords = search_params.get("keywords") or []
        file_ids = search_params.get("file_ids") or []
        time_range = search_params.get("time_range") or ""
        top_k = search_params.get("top_k") or 3

        result = {
            "intent": intent,
            "need_full_context": need_full_context,
            "search_params": {
                "keywords": keywords,
                "file_ids": file_ids,
                "time_range": time_range,
                "top_k": top_k,
            },
        }

        logger.info(f"✅ Router 意图: {intent}, keywords={len(keywords)}, file_ids={file_ids}")
        return result

    async def neural_route(self, history_summary: str, current_input: str, recent_messages: List[Dict] = None) -> dict:
        """
        Execute Neural Routing with Safety Truncation and Direct Context Injection.
        """
        # --- DIAGNOSTIC LOGGING START ---
        h_len = len(history_summary) if history_summary else 0
        r_len = len(recent_messages) if recent_messages else 0
        i_len = len(current_input) if current_input else 0
        logger.info(f"━━━ PHASE 1: NEURAL ROUTER ━━━")
        logger.info(f"📥 Input: SummaryLen={h_len} | RecentMsgs={r_len} | QueryLen={i_len}")
        # --- DIAGNOSTIC LOGGING END ---

        # --- SAFETY: Truncate history to avoid 'Payload Too Large' / Timeout ---
        safe_history = history_summary
        if history_summary and len(history_summary) > 3000:
            safe_history = "...(truncated)..." + history_summary[-3000:]
            logger.warning(f"⚠️ History truncated for Router (len={len(history_summary)} -> 3000)")
        # -----------------------------------------------------------------------

        # [Strategy Check] Bypass Router if 'intervention' mode is set
        tuning_config = config_manager.get_config("router_tuning")
        strategy = tuning_config.get("router.strategy", "routing")
        
        if strategy == "intervention":
            logger.info("⚡ Router Strategy: INTERVENTION (Skipping Router LLM -> Force Chat)")
            return {
                "needs_search": False,
                "intent": "chat",
                "confidence": 1.0,
                "keywords": [],
                "filters": {},
                "memory_distillation": "[System] Strategy > Intervention_Chat",
                "thought_process": "Forced Intervention Strategy Active (Chat Only)"
            }

        # 1. Build Prompt
        DEFAULT_ROUTER_PROMPT = """You are the INTENT ROUTER for Memex.
Your job is to classify user queries into one of the following INTENTS and extract parameters.

### Intents:
1. **search**: User wants to find specific information or files.
2. **chat**: User is casually chatting or asking general questions (logic/knowledge) without needing files.
3. **analyze**: User wants to READ specific files (by filename or ID) or wants "verbatim/full content" analysis.
4. **export**: User explicitly wants to DOWNLOAD, PACK, ARCHIVE, or SAVE files as a single document.
   - Keywords: "打包", "下载", "导出", "save as", "export", "download", "合并", "存档".
   - Action: Set intent="export". EXTRACT search_params (keywords, time_range) to find WHAT to export.
   - Example: "Download medical reports from last year" -> intent="export", keywords=["medical"], time_range="2024".

### JSON Output Format:
{
  "reasoning": "Brief thought process",
  "router": {
    "intent": "search|chat|analyze|export",
    "needs_search": boolean,
    "confidence": float
  },
  "search_payload": {
    "keywords": ["keyword1", "keyword2"],
    "time_hint": "last year",
    "file_type_hint": "pdf"
  }
}
"""
        system_prompt = prompt_manager.get("system.router_main", default=DEFAULT_ROUTER_PROMPT)
        
        # Construct Recent Context String
        recent_context_str = ""
        if recent_messages:
            # Take last 3-5 messages
            msgs_to_show = recent_messages[-5:]
            lines = []
            for m in msgs_to_show:
                role = m.get('role', 'unknown').upper()
                content = m.get('content', '')
                # Truncate long messages in router context to save tokens
                if len(content) > 200:
                    content = content[:200] + "..."
                lines.append(f"{role}: {content}")
            recent_context_str = "\n".join(lines)

        user_content = f"""
# Context
History Summary: {safe_history}

Recent Dialogue (Live Context):
{recent_context_str}

# Current Input
User: {current_input}
"""

        try:
            # 2. Call LLM (Using positional arg logic) with retry
            import asyncio
            max_retries = 2
            last_err = None
            response = None
            for attempt in range(max_retries):
                try:
                    response = await self.ai_service.chat(
                        user_content,
                        system_prompt=system_prompt,
                    )
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(f"⚠️ Router call failed (attempt {attempt+1}/{max_retries}): {e}")
                    err_str = str(e).lower()
                    if ("api key" in err_str) or ("invalid" in err_str) or ("频率" in err_str) or ("配额" in err_str) or ("quota" in err_str) or ("rate" in err_str):
                        break
                    await asyncio.sleep(1 * (attempt + 2))  # 退避 2s,3s
            if response is None:
                raise last_err

            # 3. Parse JSON
            router_response = self._parse_response(response)

            # 4. Extract Data
            needs_search = router_response.router.needs_search
            confidence = router_response.router.confidence
            needs_clarification = router_response.router.needs_clarification
            clarification_question = router_response.router.clarification_question
            
            keywords = router_response.search_payload.keywords
            memory_distillation = router_response.memory_distillation
            thought_process = router_response.thought_process
            
            # 4.1 Convert Semantic Hints to Legacy Filters
            time_hint = router_response.search_payload.time_hint
            file_type_hint = router_response.search_payload.file_type_hint
            
            # Build filters from hints (with fallback to raw filters if provided)
            raw_filters = router_response.search_payload.filters or RouterFilters()
            
            # Time: Semantic hint -> Backend code
            time_range = raw_filters.time_range  # Fallback to old format
            if time_hint:
                # Check exact match first
                if time_hint in TIME_HINT_MAP:
                    time_range = TIME_HINT_MAP[time_hint]
                # Check if it looks like a date (e.g., "2024年11月", "11月")
                elif "月" in time_hint or "年" in time_hint:
                    # Extract year-month format: "2024年11月" -> "2024-11"
                    import re
                    match = re.search(r'(\d{4})年?(\d{1,2})月', time_hint)
                    if match:
                        time_range = f"{match.group(1)}-{match.group(2).zfill(2)}"
                    else:
                        match = re.search(r'(\d{1,2})月', time_hint)
                        if match:
                            from datetime import datetime
                            current_year = datetime.now().year
                            time_range = f"{current_year}-{match.group(1).zfill(2)}"
                logger.info(f"🕐 Time hint '{time_hint}' -> filter '{time_range}'")
            
            # File Type: Semantic hint -> Backend code
            file_type = raw_filters.file_type  # Fallback to old format
            if file_type_hint and file_type_hint in FILE_TYPE_MAP:
                file_type = FILE_TYPE_MAP[file_type_hint]
                logger.info(f"📁 File type hint '{file_type_hint}' -> filter '{file_type}'")
            
            filters = RouterFilters(time_range=time_range, file_type=file_type)

            # Logic: Ambiguity Check
            if needs_clarification:
                logger.info(f"🤔 Router Hesitation: {clarification_question}")
                return {
                    "intent": "ambiguous",
                    "needs_search": False,
                    "confidence": confidence,
                    "clarification_question": clarification_question,
                    "thought_process": thought_process,
                    "memory_distillation": memory_distillation
                }

            # Logic: If NO search, empty keywords
            if not needs_search:
                keywords = []
                filters = RouterFilters()

            # 5. Log Success
            if memory_distillation:
                logger.info(f"📝 Memory Distillation: {memory_distillation}")

            logger.info(
                f"✅ Router Decision: search={needs_search}, keywords={len(keywords)}, tag={memory_distillation}"
            )
            logger.info(f"━━━ PHASE 1: COMPLETE ━━━")

            # 6. Return Flattened Dict
            final_intent = router_response.router.intent
            # Fallback: if model says 'search' but needs_search is False -> chat
            if final_intent == "search" and not needs_search:
                final_intent = "chat"
            # Fallback: if model says 'export' but needs_search is False, force search (export needs files)
            if final_intent == "export":
                needs_search = True

            return {
                "needs_search": needs_search,
                "confidence": confidence,
                "keywords": keywords,
                "filters": filters.dict(),
                "intent": final_intent,  # Use model's explicit intent
                "memory_distillation": memory_distillation,
                "thought_process": thought_process,
            }

        except Exception as e:
            logger.error(f"❌ Neural Router Failed: {e}")
            # SAFE FALLBACK: Default to CHAT (Not Search) to stop the loop
            return {
                "needs_search": False,
                "intent": "chat",
                "confidence": 0.5,
                "keywords": [],
                "memory_distillation": f"[System] Error > {str(e)[:20]}",
                "thought_process": "Fallback due to error",
            }

