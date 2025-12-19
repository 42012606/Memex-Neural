import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.models.chat import ChatMessage
from src.models.archive import ArchiveRecord, FileType
from src.services.ai_service import AIService
from src.core.database import SessionLocal

logger = logging.getLogger(__name__)

class ChatDistiller:
    """
    Nightly service to distill (summarize) chat history into daily reports.
    """
    
    def __init__(self, db: Session = None):
        self.db = db or SessionLocal()
        self.ai_service = AIService() # Uses default router model (usually fast/cheap)

    def run_daily_distillation(self, target_date: datetime = None) -> bool:
        """
        Main entry point. Summarizes chats from the target_date (default: yesterday).
        """
        if not target_date:
            target_date = datetime.now() - timedelta(days=1)
            
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        date_str = start_of_day.strftime("%Y-%m-%d")
        logger.info(f"Starting Chat Distillation for date: {date_str}")
        
        # 1. Fetch messages
        messages = self._fetch_messages(start_of_day, end_of_day)
        if not messages:
            logger.info(f"No messages found for {date_str}. Skipping.")
            return False
            
        # 2. Group by Session
        sessions = self._group_by_session(messages)
        logger.info(f"Found {len(messages)} messages across {len(sessions)} sessions.")
        
        # 3. Summarize each session
        session_summaries = []
        for session_id, msgs in sessions.items():
            summary = self._summarize_session(session_id, msgs)
            if summary:
                session_summaries.append(summary)
                
        if not session_summaries:
            logger.info("No valid summaries generated.")
            return False
            
        # 4. Generate Daily Report Content
        report_content = self._generate_report_content(date_str, session_summaries)
        
        # 5. Save as Archive
        self._save_as_archive(date_str, report_content)
        
        logger.info(f"Successfully created Daily Chat Report for {date_str}")
        return True

    def _fetch_messages(self, start: datetime, end: datetime) -> List[ChatMessage]:
        return (
            self.db.query(ChatMessage)
            .filter(ChatMessage.created_at >= start, ChatMessage.created_at <= end)
            .order_by(ChatMessage.created_at)
            .all()
        )

    def _group_by_session(self, messages: List[ChatMessage]) -> Dict[str, List[ChatMessage]]:
        sessions = {}
        for msg in messages:
            # Handle messages with no session_id (grouped into 'untagged')
            sid = msg.session_id or "untagged"
            if sid not in sessions:
                sessions[sid] = []
            sessions[sid].append(msg)
        return sessions

    def _summarize_session(self, session_id: str, messages: List[ChatMessage]) -> str:
        """
        Uses AI to summarize a single session flow.
        """
        if not messages:
            return ""
            
        # Format conversation
        conversation_text = "\n".join([f"{msg.role.upper()}: {msg.content}" for msg in messages])
        
        # Truncate if too huge (safety check, though model should handle reasonable daily volume per session)
        if len(conversation_text) > 10000:
             conversation_text = conversation_text[:10000] + "\n...(truncated)..."

        from src.core.prompt_manager import prompt_manager
        prompt_template = prompt_manager.get("chat_distiller.daily_report", default="""
Analyze the following chat session (ID: {session_id}).
Identify the main topics discussed, user intent, and key outcomes/decisions.

Conversation:
{conversation_text}

Output format:
- **Topic**: [Brief Topic Name]
- **Details**: [Summary of discussion]
- **Action Items**: [If any]
""")
        prompt = prompt_template.format(session_id=session_id, conversation_text=conversation_text)
        
        try:
            # Using generate_text for simplicity
            response = self.ai_service.generate_text(prompt=prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"Failed to summarize session {session_id}: {e}")
            return f"Session {session_id}: Summary failed."

    def _generate_report_content(self, date_str: str, summaries: List[str]) -> str:
        content = [
            f"# Daily Chat Report: {date_str}",
            f"> Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Session Summaries"
        ]
        
        for i, summary in enumerate(summaries, 1):
            content.append(f"### Session {i}")
            content.append(summary)
            content.append("\n---\n")
            
        return "\n".join(content)

    def _save_as_archive(self, date_str: str, content: str):
        # Check if already exists to avoid duplicates
        filename = f"{date_str}-DailyChatReport.md"
        
        existing = (
            self.db.query(ArchiveRecord)
            .filter(ArchiveRecord.filename == filename)
            .first()
        )
        
        if existing:
            logger.info(f"Overwriting existing report for {date_str}")
            existing.full_text = content
            existing.processed_at = datetime.now()
            # Reset vectorization status so it gets re-embedded if needed
            existing.is_vectorized = 0 
        else:
            new_archive = ArchiveRecord(
                filename=filename,
                original_filename=filename,
                file_type=FileType.MEMOS.value,  # Ensure FileType.MEMOS is handled in UI/Logic
                category="DailyReport",
                summary=f"Daily chat summary for {date_str}",
                full_text=content,
                relative_path=f"memories/{filename}", # Virtual path
                file_size=len(content.encode('utf-8')),
                meta_data={"date": date_str, "type": "daily_report"},
                is_vectorized=0
            )
            self.db.add(new_archive)
        
        self.db.commit()

if __name__ == "__main__":
    # Test run
    distiller = ChatDistiller()
    distiller.run_daily_distillation()
