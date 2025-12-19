import logging
from typing import Optional, Dict
from sqlalchemy.orm import Session
from src.core.database import SessionLocal
from src.models.prompt_config import PromptConfig
from datetime import datetime

logger = logging.getLogger(__name__)

class PromptManager:
    """
    PromptOps Core Service.
    Manage prompt templates with database storage and memory caching.
    Singleton pattern.
    """
    _instance = None
    _cache: Dict[str, str] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptManager, cls).__new__(cls)
            cls._instance._load_cache()
        return cls._instance

    def _load_cache(self):
        """Initial load of all prompts into memory."""
        db = SessionLocal()
        try:
            configs = db.query(PromptConfig).all()
            self._cache = {cfg.key: cfg.content for cfg in configs}
            logger.info(f"🧠 PromptManager loaded {len(self._cache)} prompts into cache.")
        except Exception as e:
            logger.error(f"❌ Failed to load prompt cache: {e}")
        finally:
            db.close()

    def get(self, key: str, default: Optional[str] = None) -> str:
        """
        Get a prompt by key.
        1. Access memory cache first (Fast).
        2. If missing, return default.
        """
        if key in self._cache:
            return self._cache[key]
        
        if default:
            # Optionally: we could auto-create the default in DB if missing?
            # For now, just return default to be safe and non-intrusive.
            return default
            
        logger.warning(f"⚠️ Prompt key not found: {key}")
        return ""

    def set(self, key: str, content: str, group: str = "general", description: str = None, role: str = None) -> PromptConfig:
        """
        Update or create a prompt.
        Updates DB and refreshes cache immediately (Hot Reload).
        """
        db = SessionLocal()
        try:
            config = db.query(PromptConfig).filter(PromptConfig.key == key).first()
            if config:
                config.content = content
                config.version += 1
                if group: config.group = group
                if description is not None: config.description = description
                if role is not None: config.role = role
                # Update timestamp handled by onupdate in model? 
                # Model has onupdate=datetime.now but explicit update is safer for verification
                config.updated_at = datetime.now()
            else:
                config = PromptConfig(
                    key=key, 
                    content=content, 
                    group=group, 
                    description=description,
                    role=role,
                    version=1
                )
                db.add(config)
            
            db.commit()
            db.refresh(config)
            
            # Update Cache
            self._cache[key] = content
            logger.info(f"🔄 Prompt updated: {key} (v{config.version})")
            return config
        except Exception as e:
            db.rollback()
            logger.error(f"❌ Failed to set prompt {key}: {e}")
            raise e
        finally:
            db.close()

    def refresh(self):
        """Force reload cache from DB."""
        self._load_cache()

    def list_all(self):
        """Return all prompt configs (meta-data included) for UI."""
        db = SessionLocal()
        try:
            configs = db.query(PromptConfig).all()
            return [c.to_dict() for c in configs]
        finally:
            db.close()

    def initialize_defaults(self, db: Session):
        """
        初始化默认 Prompt (Seeding)
        """
        try:
            # Always check for missing defaults (Upsert strategy)
            if True:
                # Get existing keys to avoid overwriting user customizations
                existing_keys = {p[0] for p in db.query(PromptConfig.key).all()}
                
                # Define some core defaults
                defaults = [
                    {
                        "key": "system.chat_default",
                        "group": "system",
                        "role": "Memex 助手",
                        "content": "你是由 Memex 驱动的智能个人知识助手。你的风格是专业、简洁、高效。你的核心能力是管理用户的文件知识库，并基于检索到的上下文回答问题。请始终使用中文与用户交流，除非用户要求其他语言。",
                        "description": "默认聊天系统提示词 (Memex Persona)"
                    },
                    {
                        "key": "tasks.summarization",
                        "group": "tasks",
                        "role": "摘要生成员",
                        "content": "请简要总结以下内容，提取关键信息点，并保持客观。",
                        "description": "默认总结提示词 (用于文档总结)"
                    },
                    {
                        "key": "system.router_main",
                        "group": "system",
                        "role": "意图法官",
                        "content": """# 角色
你是 Memex 的意图法官。根据用户输入和历史上下文，判断用户是想搜索知识库还是闲聊。

# 输入
- `history_summary`: 历史对话摘要
- `recent_messages`: 最近对话原文
- `current_input`: 用户当前输入

# 核心任务

## 1. 意图分类
判断 `needs_search`:
- **true** (需要搜索): 用户在询问事实、寻找文件、回忆信息、查找记录
- **false** (不需要): 用户在打招呼、闲聊、问通用知识问题

## 2. 反犹豫机制 (Anti-Hallucination)
如果你不确定用户在指哪个文件（如"那个发票"可能匹配多个），设置 `needs_clarification=true` 并在 `clarification_question` 中提问。**宁可多问，不可乱猜。**

## 3. 关键词提取
提取用户查询中的核心概念词，进行语义扩展：
- 动作词 → 证据词 (买/消费 → 发票、账单、收据)
- 主题词 → 文档词 (健康 → 体检报告、病历)
- 保留具体名词 (文件名、日期、金额等)

## 4. 时间理解
用自然语言描述时间范围，后端会自动处理映射：
- "刚刚/刚才/just now" → `time_hint: "非常近期"`
- "最近/最新/latest" → `time_hint: "近期"`
- "今天/today" → `time_hint: "今天"`
- "本周/this week" → `time_hint: "本周"`
- "本月/上个月/11月" → `time_hint: "本月"` 或具体月份如 `"2024年11月"`
- 无明确时间暗示 → `time_hint: null`

## 5. 文件类型
- 默认不限制 (`file_type_hint: null`)
- 仅当用户明确说"图片/照片/截图"时设为 `"图片"`
- 仅当用户明确说"音频/录音/语音"时设为 `"音频"`
- 仅当用户明确说"文档/PDF/文本"时设为 `"文档"`

## 6. 记忆蒸馏 (必须)
将用户输入压缩成一个标签，格式: `[主题] 行为 > 细节`
即使不需要搜索也必须生成。

# 输出格式 (JSON)
{
  "thought_process": "你的推理过程 (<50字)",
  "router": {
    "needs_search": true/false,
    "confidence": 0.0-1.0,
    "needs_clarification": true/false,
    "clarification_question": "追问内容或null"
  },
  "search_payload": {
    "keywords": ["关键词1", "关键词2"],
    "time_hint": "非常近期/近期/今天/本周/本月/2024年11月/null",
    "file_type_hint": "图片/文档/音频/视频/null"
  },
  "memory_distillation": "[主题] 行为 > 细节"
}
""",
                        "description": "Router 核心系统提示词 (决定搜索/闲聊)"
                    },
                    {
                        "key": "system.file_analyze",
                        "group": "system",
                        "role": "归档分析员",
                        "content": """
# Role
你是 Memex 的归档分析员。你的任务是从文件内容中提取元数据，并生成规范的文件名。

# 输入
- 当前时间: {current_time}
- 文件名: "{filename}"
- 内容:
{content_text}

# 核心任务
1. **生成文件名**: 格式 `YYYYMMDD_核心内容摘要{file_ext}`。日期优先用文档内日期，无日期则用当前日期。
2. **提取元数据**: 
   - 摘要 (`summary`): <50字，精炼概括。
   - 标签 (`tags`): 1-5个中文关键词。
   - 分类 (`category`): Medical/Finance/Work/Personal/Unsorted。

# 输出格式 (纯 JSON)
{{
  "suggested_filename": "20231115_体检报告.txt",
  "semantic": {{
    "category": "Medical",
    "tags": ["体检", "报告"],
    "summary": "2023年11月15日体检报告，各项指标正常。"
  }},
  "structured": {{
    "date": "2023-11-15",
    "money": null
  }}
}}
""",
                        "title": "文件归档分析 Prompt (自动重命名/分类)"
                    },
                    {
                        "key": "vision.analyze",
                        "group": "vision",
                        "role": "视觉分析员",
                        "content": """
请详细分析这张图片，并以严格的 JSON 格式输出结果。
你需要提取以下信息：
1. visual_summary: 图片内容的详细视觉描述。
2. objects: 图中包含的主要物体列表。
3. ocr_text: 图中包含的所有可见文字（保持原始排版和换行）。
4. scene_type: 场景类型（如：截图、照片、海报、文档、发票等）。
5. tags: 5-10 个相关的语义标签。

JSON 格式示例：
{
    "visual_summary": "...",
    "objects": ["obj1", "obj2"],
    "ocr_text": "...",
    "scene_type": "...",
    "tags": ["tag1", "tag2"]
}
""",
                        "description": "统一视觉模型分析 Prompt (返回 JSON)"
                    },
                    {
                        "key": "gardener.semantic_split",
                        "group": "gardener",
                        "role": "语义手术刀",
                        "content": "请将以下文本切分成语义完整的段落。返回一个字符串列表 (JSON List of Strings)。\n- 保持每个段落的独立性\n- 适合作为向量检索的切片\n- 仅输出 JSON，不要其他废话\n\n文本内容:\n{{ text }}",
                        "description": "将长文本分割为语义完整的片段 (返回 JSON Array)"
                    },
                    {
                        "key": "gardener.context_enrich",
                        "group": "gardener",
                        "role": "语境补全师",
                        "content": "你是语境补全师。你的任务是改写下方的`文本切片`，使其独立完整。\n\n1. 利用`元数据`补充缺失的时间、标题或背景。\n2. 将代词 (他/它/那个) 替换为具体的名称。\n\n元数据: {{ metadata }}\n文本切片: \"{{ chunk_text }}\"\n\n请直接输出改写后的文本，不要加引号或前缀。",
                        "description": "为切片补充缺失的上下文 (代词替换/背景注入)"
                    },
                    {
                        "key": "chat_distiller.daily_report",
                        "group": "tasks",
                        "role": "日报主编",
                        "content": """
Analyze the following chat session (ID: {session_id}).
Identify the main topics discussed, user intent, and key outcomes/decisions.

Conversation:
{conversation_text}

Output format:
- **Topic**: [Brief Topic Name]
- **Details**: [Summary of discussion]
- **Action Items**: [If any]
""",
                        "description": "生成每日对话摘要报告"
                    },
                    {
                        "key": "tasks.daily_briefing",
                        "group": "tasks",
                        "role": "简报生成员",
                        "content": """
请根据以下 Memex 过去 24 小时内归档的文件摘要，生成一份“每日简报” (Daily Briefing)。

要求：
1. **结构清晰**：使用 Markdown 格式，包含标题、关键洞察、分类汇总。
2. **洞察深刻**：不要流水账，尝试发现不同文件之间的联系或潜在趋势。
3. **行动建议**：如果内容涉及待办或任务，请在末尾列出可能有用的“Suggested Actions”。
4. **语言风格**：专业、简洁、高效 (JARVIS 风格)。

【今日归档内容摘要】：
{{ content_summary }}
""",
                        "description": "生成每日文件归档简报"
                    }
                ]
                
                for p in defaults:
                    if p["key"] not in existing_keys:
                        # New prompt: Create full
                        self.set(p["key"], p["content"], p["group"], p.get("description", ""), p.get("role", None))
                        logger.info(f"✨ Initialized new prompt: {p['key']}")
                    else:
                        # Existing prompt: Backfill missing Role/Metadata ONLY
                        # Do NOT overwrite content to preserve user edits
                        current_config = db.query(PromptConfig).filter(PromptConfig.key == p["key"]).first()
                        if current_config:
                            changed = False
                            # Backfill Role
                            if not current_config.role and p.get("role"):
                                current_config.role = p["role"]
                                changed = True
                            
                            # FORCE UPDATE for Critical Core Prompts to ensure logic upgrades are applied
                            if p["key"] in ["system.router_main", "system.chat_default"]:
                                if current_config.content != p["content"]:
                                    current_config.content = p["content"]
                                    changed = True
                                if current_config.description != p["description"]:
                                    current_config.description = p["description"]
                                    changed = True
                            
                            # Note: We purposely do NOT update 'group' or 'description' aggressively to respect user changes
                            # unless we want to enforce schema migrations.
                            
                            if changed:
                                db.commit()
                                logger.info(f"🔄 Backfilled metadata for: {p['key']}")

                
                # Cleanup: Remove legacy/redundant prompts
                try:
                    from src.core.database import SessionLocal
                    cleanup_db = SessionLocal()
                    deleted = cleanup_db.query(PromptConfig).filter(PromptConfig.key.in_(["system.chat_system_prompt", "system.router_schema", "system.router_v2"])).delete()
                    if deleted:
                        cleanup_db.commit()
                        logger.info("🧹 Removed legacy prompt: system.chat_system_prompt")
                        # Update cache if needed
                        if "system.chat_system_prompt" in self._cache:
                            del self._cache["system.chat_system_prompt"]
                    cleanup_db.close()
                except Exception as ce:
                    logger.warning(f"⚠️ Prompt cleanup warning: {ce}")
                
                logger.info("✅ Default prompts check completed.")
        except Exception as e:
            logger.error(f"❌ 初始化默认 Prompt 失败: {e}")

# Global Instance
prompt_manager = PromptManager()
