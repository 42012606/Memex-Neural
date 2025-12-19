#!/usr/bin/env python3
"""
Force Reset Tables Script

This script DROPS the following tables to allow them to be recreated with the correct schema:
- chat_messages (has FK to chat_sessions, must be dropped first)
- chat_sessions
- ai_models

⚠️  WARNING: This will PERMANENTLY DELETE all data in these tables!
After running this script, restart the backend to recreate the tables with the correct schema.
"""

import sys
import os
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path
sys.path.append(os.getcwd())

from sqlalchemy import create_engine, text, inspect
from src.core.config import settings

def force_reset_tables():
    """Drop the specified tables to allow recreation with correct schema"""
    
    logger.info("=" * 60)
    logger.info("FORCE RESET TABLES SCRIPT")
    logger.info("=" * 60)
    logger.warning("⚠️  This will PERMANENTLY DELETE all data in:")
    logger.warning("   - chat_messages")
    logger.warning("   - chat_sessions")
    logger.warning("   - ai_models")
    logger.info("=" * 60)
    
    # Safety confirmation
    response = input("\nAre you sure you want to proceed? Type 'YES' to continue: ")
    if response != 'YES':
        logger.info("Operation cancelled by user.")
        return
    
    # Connect to database
    db_url_safe = settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL
    logger.info(f"Connecting to database: {db_url_safe}")
    
    try:
        engine = create_engine(settings.DATABASE_URL)
        inspector = inspect(engine)
        
        # Tables to drop (in order: child tables first, then parent tables)
        tables_to_drop = [
            'chat_messages',   # Has FK to chat_sessions, must be dropped first
            'chat_sessions',
            'ai_models'
        ]
        
        # Check which tables exist
        existing_tables = []
        for table_name in tables_to_drop:
            if inspector.has_table(table_name):
                existing_tables.append(table_name)
                logger.info(f"✓ Found table: {table_name}")
            else:
                logger.info(f"○ Table does not exist: {table_name} (skipping)")
        
        if not existing_tables:
            logger.info("No tables to drop. All tables are already missing.")
            return
        
        logger.info(f"\nWill drop {len(existing_tables)} table(s): {', '.join(existing_tables)}")
        
        # Drop tables in transaction
        with engine.begin() as conn:
            for table_name in existing_tables:
                try:
                    logger.info(f"Dropping table: {table_name}...")
                    # Use CASCADE to handle any remaining foreign key constraints
                    conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
                    logger.info(f"✅ Successfully dropped: {table_name}")
                except Exception as e:
                    logger.error(f"❌ Failed to drop {table_name}: {e}")
                    raise
        
        # Verify tables were dropped
        logger.info("\nVerifying tables were dropped...")
        inspector = inspect(engine)
        remaining_tables = []
        for table_name in tables_to_drop:
            if inspector.has_table(table_name):
                remaining_tables.append(table_name)
                logger.warning(f"⚠️  Table still exists: {table_name}")
        
        if remaining_tables:
            logger.error(f"❌ Some tables were not dropped: {remaining_tables}")
            logger.error("   You may need to manually drop them or check for foreign key constraints")
        else:
            logger.info("✅ All specified tables have been dropped")
        
        logger.info("\n" + "=" * 60)
        logger.info("✅ Drop operation completed!")
        logger.info("=" * 60)
        logger.info("\nNext steps:")
        logger.info("1. Restart your backend server (python -m src.main or uvicorn)")
        logger.info("2. The tables will be automatically recreated with the correct schema:")
        logger.info("   - chat_sessions.id will be VARCHAR(36) (UUID)")
        logger.info("   - chat_sessions.user_id will exist")
        logger.info("   - ai_models.config will be JSONB")
        logger.info("3. If tables still have issues, the init_db() function will now")
        logger.info("   automatically add missing columns (user_id, config)")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        logger.exception(e)
        sys.exit(1)

if __name__ == "__main__":
    try:
        force_reset_tables()
    except KeyboardInterrupt:
        logger.info("\n\nOperation cancelled by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
