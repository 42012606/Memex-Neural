import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.core.database import SessionLocal
from src.core.config import settings
from src.models.archive import ArchiveRecord
from src.models.chat import ChatMessage
from src.models.session import ChatSession
from src.models.session import ChatSession
from src.services.ai_service import AIService
from src.services.distillation import DistillationService

logger = logging.getLogger(__name__)


def _today_range() -> tuple[datetime, datetime]:
    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=1)
    return start, end


async def run_daily_summary(user_id: int = 1) -> dict:
    """Job A: 生成每日 Summary Markdown 文件"""
    db = SessionLocal()
    try:
        start, end = _today_range()
        records = (
            db.query(ArchiveRecord)
            .filter(
                ArchiveRecord.user_id == user_id,
                ArchiveRecord.processed_at >= start,
                ArchiveRecord.processed_at < end,
            )
            .all()
        )
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.user_id == user_id, ChatSession.updated_at >= start)
            .all()
        )
        session_ids = [s.id for s in sessions]
        messages = []
        if session_ids:
            messages = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.user_id == user_id,
                    ChatMessage.session_id.in_(session_ids),
                    ChatMessage.created_at >= start,
                )
                .order_by(ChatMessage.created_at)
                .all()
            )

        uploads_block = "\n".join(
            [
                f"- [{r.id}] {r.filename} ({r.category}) {r.summary or ''}"
                for r in records
            ]
        ) or "（今日无上传）"

        dialog_block = "\n".join(
            [f"- {m.role}: {m.content}" for m in messages]
        ) or "（今日无对话）"

        prompt = f"""
你是 Memex 的每日记录官，请生成 Markdown 日报。
内容包含：
1) 今日上传列表（保持简洁）。
2) 今日对话与决策要点。
3) 关键行动项（如有）。

请输出 Markdown，语气简洁、结构分节。

【今日上传】
{uploads_block}

【今日对话】
{dialog_block}
"""

        ai = AIService()
        ai_result = await ai.chat(query=prompt, context="")
        summary_md = ai_result.get("reply", "") if isinstance(ai_result, dict) else str(ai_result)

        log_dir = Path(settings.USER_DATA_DIR) / "Memex_Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fname = f"Daily_Summary_{start.strftime('%Y-%m-%d')}.md"
        target = log_dir / fname
        target.write_text(summary_md, encoding="utf-8")

        logger.info(f"✅ Daily Summary written to {target}")
        return {"status": "ok", "file": str(target)}
    except Exception as e:
        logger.error(f"❌ Daily Summary failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


async def run_memory_distillation(user_id: int = 1) -> dict:
    """Job B: 蒸馏用户偏好，更新 user_profile.md"""
    db = SessionLocal()
    try:
        start, _ = _today_range()
        sessions = (
            db.query(ChatSession)
            .filter(ChatSession.user_id == user_id, ChatSession.updated_at >= start)
            .all()
        )
        session_ids = [s.id for s in sessions]
        if not session_ids:
            return {"status": "skipped", "message": "no sessions today"}

        messages = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.user_id == user_id,
                ChatMessage.session_id.in_(session_ids),
                ChatMessage.created_at >= start,
            )
            .order_by(ChatMessage.created_at)
            .all()
        )

        convo_block = "\n".join(
            [f"{m.role.upper()}: {m.content}" for m in messages]
        )

        profile_path = Path(settings.DATA_DIR) / "user_profile.md"
        current_profile = ""
        if profile_path.exists():
            current_profile = profile_path.read_text(encoding="utf-8")

        prompt = f"""
你是 Memex 的“偏好蒸馏”助手，请基于今日真实会话提炼**长期偏好**，严禁臆测或编造。

规则（务必遵守）：
1) Anti-Hallucination: 严禁记录具体且未经证实的文件名/路径（如 “沈阳.m4a”）；只总结通用行为模式（如“用户习惯按类型归档”）。
2) Trait vs State: 严禁写入临时/一次性任务需求（如“想查11月账单”）；只保留长期偏好/习惯（如“关注医疗支出”）。
3) Anti-Pinyin Tags: 如发现拼音标签或拼音污染，必须加入规则：**强制使用中文标签或常见英文单词，禁止拼音/拼音下划线**。
4) 输出 3-8 条要点，中文，必要时引用原句片段佐证；未知则写“未提及”，不要猜测；如需修正用“修正/新增”表述。

【当前 User Profile】
{current_profile}

【今日对话】
{convo_block}
"""

        ai = AIService()
        ai_result = await ai.chat(query=prompt, context="")
        distilled = ai_result.get("reply", "") if isinstance(ai_result, dict) else str(ai_result)

        stamp = datetime.now().strftime("%Y-%m-%d")
        append_block = f"\n\n## 更新 {stamp}\n{distilled}\n"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        with profile_path.open("a", encoding="utf-8") as f:
            f.write(append_block)

        logger.info(f"✅ Profile updated via distillation ({profile_path})")
        return {"status": "ok", "profile": str(profile_path)}
    except Exception as e:
        logger.error(f"❌ Memory distillation failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


async def run_nightly_jobs():
    """便于一次性串行触发两个任务"""
    daily = await run_daily_summary()
    distill = await run_memory_distillation()
    distill = await run_memory_distillation()
    
    # [New] Nightly Gardener
    gardener_result = "not run"
    db = SessionLocal()
    try:
        distillation_service = DistillationService(db)
        gardener_result = await distillation_service.run_nightly_gardener()
    except Exception as e:
        gardener_result = f"error: {str(e)}"
    finally:
        db.close()
        
    return {"daily_summary": daily, "memory_distillation": distill, "gardener": gardener_result}
