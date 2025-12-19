import logging
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import func
from src.core.database import SessionLocal
from src.plugins.gardener_plugin import RefinerAgent
from src.services.chat_distiller import ChatDistiller
from src.models.storage import StorageRoot
from src.models.vector_node import VectorNode
from src.models.archive import ArchiveRecord
from src.models.proposal import Proposal
from src.core.config_manager import config_manager
from src.services.notification import send_webhook_notification

logger = logging.getLogger(__name__)

async def run_nightly_jobs():
    """
    Execute all nightly maintenance tasks.
    """
    logger.info("🌙 Starting Nightly Jobs...")
    
    # 1. Load Config
    config = config_manager.get_config("nightly")
    if not config.get("enable", True):
        logger.info("⏸️ Nightly jobs disabled in config. Skipping.")
        return

    db = SessionLocal()
    try:
        stats = {
            "archives_refined": 0,
            "proposals_generated": 0,
            "errors": 0
        }

        # 2. Run Gardener Refiner
        if config.get("auto_refine", False):
            # TODO: Pass auto_approve=True to RefinerAgent if implemented
            pass
            
        logger.info("🌿 Running Gardener Refiner...")
        try:
            agent = RefinerAgent(db=db)
            # We count proposals before and after to get stats
            count_before = db.query(Proposal).filter(Proposal.created_at >= datetime.now().date()).count()
            
            agent.scan_and_propose()
            
            count_after = db.query(Proposal).filter(Proposal.created_at >= datetime.now().date()).count()
            stats["proposals_generated"] = count_after - count_before
            logger.info("✅ Gardener Refiner completed.")
        except Exception as e:
            logger.error(f"❌ Gardener failed: {e}")
            stats["errors"] += 1

        # 3. Generate Morning Briefing
        if config.get("morning_briefing", True):
            await generate_morning_briefing(db, stats)
            
        # 4. Run Chat Distiller (Daily Report)
        logger.info("📝 Running Chat Distiller...")
        try:
            distiller = ChatDistiller(db=db)
            report_generated = distiller.run_daily_distillation()
            if report_generated:
                stats["archives_refined"] += 1 # Treating daily report as a new 'refined' archive for stats
                logger.info("✅ Daily Chat Report generated.")
        except Exception as e:
            logger.error(f"❌ Chat Distiller failed: {e}")
            stats["errors"] += 1

    except Exception as e:
        logger.error(f"❌ Nightly Jobs failed: {e}")
    finally:
        db.close()
        logger.info("🌙 Nightly Jobs finished.")

async def generate_morning_briefing(db, stats):
    """
    Generate a summary of the last 24h activity.
    """
    logger.info("☀️ Generating Morning Briefing...")
    
    # Calculate time window (last 24h)
    since = datetime.now() - timedelta(hours=24)
    
    # 1. Collect Data
    new_archives = db.query(ArchiveRecord).filter(ArchiveRecord.created_at >= since).count()
    active_proposals = db.query(Proposal).filter(Proposal.status == "pending").count()
    
    # 2. Format Content (Markdown)
    content = {
        "title": f"Morning Briefing: {datetime.now().strftime('%Y-%m-%d')}",
        "sections": [
            {
                "icon": "auto_awesome",
                "title": "Nightly Maintenance",
                "text": f"System executed automated maintenance tasks.\n- Proposals Generated: **{stats['proposals_generated']}**\n- Errors Encountered: {stats['errors']}"
            },
            {
                "icon": "analytics",
                "title": "Daily Activity (Last 24h)",
                "text": f"- New Archives: **{new_archives}**\n- Pending Proposals: **{active_proposals}**"
            }
        ]
    }
    
    # 3. Create Proposal (Type: briefing)
    # We check if one already exists for today to avoid duplicates
    today_str = datetime.now().strftime('%Y-%m-%d')
    existing = db.query(Proposal).filter(
        Proposal.type == "morning_briefing", 
        Proposal.reasoning.like(f"%{today_str}%")
    ).first()
    
    if not existing:
        briefing = Proposal(
            type="morning_briefing",
            content=content,
            status="pending", # User needs to "Read" (Approve) it to dismiss
            reasoning=f"Automated briefing for {today_str}"
        )
        db.add(briefing)
        db.commit()
        
        # Send Notification
        send_webhook_notification("morning_briefing", {"summary": f"Morning Briefing is ready. {new_archives} new archives."})
        logger.info("✅ Morning Briefing generated.")
    else:
        logger.info("ℹ️ Morning Briefing already exists for today.")

if __name__ == "__main__":
    asyncio.run(run_nightly_jobs())
