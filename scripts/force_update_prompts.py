import sys
import os

# Add src to path
sys.path.append(os.getcwd())

# FORCE LOCALHOST for DB connection when running script locally
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_DB"] = "memex"

from src.core.database import SessionLocal
from src.models.prompt_config import PromptConfig
from src.core.prompt_manager import prompt_manager

def force_update_prompts():
    print("🚀 Starting Force Prompt Update...")
    db = SessionLocal()
    
    updates = [
        {
            "key": "system.file_analyze",
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
"""
        },
        {
            "key": "gardener.semantic_split",
            "content": "请将以下文本切分成语义完整的段落。返回一个字符串列表 (JSON List of Strings)。\n- 保持每个段落的独立性\n- 适合作为向量检索的切片\n- 仅输出 JSON，不要其他废话\n\n文本内容:\n{{ text }}"
        },
        {
            "key": "gardener.context_enrich",
            "content": "你是语境补全师。你的任务是改写下方的`文本切片`，使其独立完整。\n\n1. 利用`元数据`补充缺失的时间、标题或背景。\n2. 将代词 (他/它/那个) 替换为具体的名称。\n\n元数据: {{ metadata }}\n文本切片: \"{{ chunk_text }}\"\n\n请直接输出改写后的文本，不要加引号或前缀。"
        },
        {
            "key": "system.router_main",
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
"""
        }
    ]

    try:
        for item in updates:
            print(f"Checking {item['key']}...")
            config = db.query(PromptConfig).filter(PromptConfig.key == item['key']).first()
            if config:
                config.content = item['content']
                # Force version increment
                config.version += 1
                print(f"✅ Updated {item['key']} to v{config.version}")
            else:
                print(f"⚠️ Key {item['key']} not found in DB! Creating...")
                # Fallback to manager set if needed, but direct DB is fine here
                prompt_manager.set(item['key'], item['content'])
        
        db.commit()
        print("🎉 All prompts updated successfully!")
    except Exception as e:
        db.rollback()
        print(f"❌ Error updating prompts: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    force_update_prompts()
