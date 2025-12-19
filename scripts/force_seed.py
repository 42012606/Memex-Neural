
import sys
import os
import logging

# Force DB settings to localhost
os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_DB"] = "memex"

sys.path.append(os.getcwd())

from src.core.database import SessionLocal
from src.core.prompt_manager import prompt_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def force_seed():
    logger.info("Running manual seed initialization...")
    db = SessionLocal()
    try:
        prompt_manager.initialize_defaults(db)
        logger.info("✅ Manual seed completed.")
    except Exception as e:
        logger.error(f"❌ Seed failed: {e}")
    finally:
        db.close()
        
    # Verify count now
    prompts = prompt_manager.list_all()
    print(f"Total Prompts now: {len(prompts)}")
    for p in prompts:
        print(f" - {p['key']} ({p.get('role')})")

if __name__ == "__main__":
    force_seed()
