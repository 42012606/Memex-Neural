import logging
import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from src.models.archive import ArchiveRecord
from src.models.proposal import Proposal
from src.services.ai_service import AIService

logger = logging.getLogger(__name__)

class DistillationService:
    def __init__(self, db: Session):
        self.db = db
        self.ai_service = AIService() # Usage: AIService(service_type="reasoning") if strictly needed, but default is fine.

    async def distill_daily_briefing(self) -> dict:
        """
        1. Daily Briefing.
        2. Nightly Gardener: Generate cleanup proposals.
        """
        # --- Part 1: Briefing ---
        logger.info("🌙 Starting Nightly Distillation...")
        
        # 1. 确定时间范围 (过去 24 小时)
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=24)
        
        # 2. 查询记录
        recent_records = self.db.query(ArchiveRecord).filter(
            ArchiveRecord.processed_at >= cutoff_time,
            ArchiveRecord.category != "Daily Briefing" # 避免死循环递归
        ).all()
        
        if not recent_records:
            logger.info("💤 No new records in the last 24h. Skipping briefing.")
            return {"status": "skipped", "message": "No new records found."}
        
        logger.info(f"Found {len(recent_records)} records for distillation.")
        
        # 3. 构建 Prompt
        # 提取摘要，限制长度以防 Prompt 过长
        content_summary = ""
        for i, record in enumerate(recent_records, 1):
            if record.summary:
                content_summary += f"{i}. [{record.filename}] ({record.category}): {record.summary}\n"
            else:
                content_summary += f"{i}. [{record.filename}] ({record.category}): (No summary available)\n"
        
        from src.core.prompt_manager import prompt_manager
        
        prompt_template = prompt_manager.get("tasks.daily_briefing", default="""
请根据以下 Memex 过去 24 小时内归档的文件摘要，生成一份“每日简报” (Daily Briefing)。

要求：
1. **结构清晰**：使用 Markdown 格式，包含标题、关键洞察、分类汇总。
2. **洞察深刻**：不要流水账，尝试发现不同文件之间的联系或潜在趋势。
3. **行动建议**：如果内容涉及待办或任务，请在末尾列出可能有用的“Suggested Actions”。
4. **语言风格**：专业、简洁、高效 (JARVIS 风格)。

【今日归档内容摘要】：
{{ content_summary }}
""")
        
        prompt = prompt_template.replace("{{ content_summary }}", content_summary)
        
        # 4. 调用 AI (Reasoning Agent)
        try:
            # 使用 reasoning agent 进行深度总结
            briefing_content = await self.ai_service.chat(
                query=prompt, 
                model_id=None # Use default reasoning model
            )
        except Exception as e:
            logger.error(f"❌ AI Generation failed: {e}")
            return {"status": "error", "message": str(e)}
        
        # 5. 保存结果
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        new_record = ArchiveRecord(
            user_id=1, 
            filename=f"Daily_Briefing_{today_str}.md",
            file_type="markdown",
            category="Daily Briefing",
            summary="System generated nightly distillation of recent archives.",
            full_text=briefing_content,
            processing_status="completed",
            path="system://distillation", # 虚拟路径
            is_vectorized=0 # 简报本身暂时不需向量化，或后续异步处理
        )
        
        self.db.add(new_record)
        self.db.commit()
        self.db.refresh(new_record)
        
        logger.info(f"✅ Daily Briefing generated and saved: ID {new_record.id}")
        
        return {
            "record_id": new_record.id, 
            "briefing_preview": briefing_content[:200] + "..."
        }

    async def run_nightly_gardener(self):
        """
        Identify cleanup candidates and generate proposals.
        """
        logger.info("🌱 Starting Nightly Gardener...")
        
        # Rule 1: Find temporary files older than 7 days
        # (Assuming 'temp' in filename or Unsorted category with no tags)
        
        # NOTE: Simple heuristic for now, can be updated with AI later.
        
        cutoff_7d = datetime.datetime.now() - datetime.timedelta(days=7)
        
        candidates = self.db.query(ArchiveRecord).filter(
            ArchiveRecord.processed_at < cutoff_7d,
            (ArchiveRecord.filename.ilike("%temp%") | ArchiveRecord.filename.ilike("%screenshot%"))
        ).limit(10).all()

        if candidates:
            # Create a proposal
            files_to_clean = [{"id": r.id, "filename": r.filename, "date": str(r.processed_at)} for r in candidates]
            
            logger.info(f"🌱 Gardener found {len(candidates)} cleanup candidates. Creating proposal.")
            
            # Check if similar proposal exists? (Skip for now)
            
            proposal = Proposal(
                type="cleanup",
                content={
                    "title": f"Cleanup {len(candidates)} old temporary files",
                    "description": "Found files older than 7 days that appear to be temporary.",
                    "actions": [{"action": "delete", "file_id": f["id"]} for f in files_to_clean],
                    "details": files_to_clean
                },
                user_id=1, # Default user
                reasoning="Automatic hygiene check for old temporary files."
            )
            self.db.add(proposal)
            self.db.commit()
            return f"Generated cleanup proposal for {len(candidates)} files."
            
        return "No cleanup proposals generated."
