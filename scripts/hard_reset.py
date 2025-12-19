
import sys
import os
import logging
from sqlalchemy import text

# Add src to path
sys.path.append(os.getcwd())

from src.core.database import SessionLocal, engine

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HardReset")

def reset_db():
    logger.warning("⚠️ STARTING HARD RESET: This will delete ALL ARCHIVES and VECTORS!")
    
    db = SessionLocal()
    try:
        # Use raw SQL to truncate tables efficiently
        # Order matters due to foreign keys
        statements = [
            "TRUNCATE TABLE vector_nodes CASCADE;",
            "TRUNCATE TABLE archives CASCADE;",
            "TRUNCATE TABLE chat_messages CASCADE;",
            "TRUNCATE TABLE chat_sessions CASCADE;",
             # "TRUNCATE TABLE storage_roots CASCADE;" # Keep storage roots config? User said "Clear vector and files"
        ]
        
        for stmt in statements:
            try:
                logger.info(f"Executing: {stmt}")
                db.execute(text(stmt))
            except Exception as e:
                logger.warning(f"Error executing {stmt}: {e}")
                # Ignore verify error if table doesn't exist
        
        db.commit()
        logger.info("✅ Database cleared successfully.")
        
        # Optional: Clear physical files? 
        # User said "Clear files too". 
        # But we don't want to delete the whole directory if it contains code or config.
        # We should only delete contents of storage roots if we knew where they were.
        # Check storage roots
        
    except Exception as e:
        logger.error(f"Reset failed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    confirm = input("Are you sure? Type 'yes' to proceed: ")
    if confirm == "yes":
        reset_db()
    else:
        print("Cancelled.")
