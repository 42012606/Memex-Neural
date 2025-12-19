import os
import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.core.database import SessionLocal

logger = logging.getLogger(__name__)

class MigrationManager:
    """
    Simple SQL-based Migration Manager.
    Scans `migrations/` directory for .sql files and executes them in order.
    Tracks applied migrations in `_migrations` table.
    """
    
    def __init__(self, migration_dir: str = "migrations"):
        # Assuming run from project root
        self.migration_dir = migration_dir

    def _ensure_migration_table(self, db: Session):
        """Create migration tracking table if not exists."""
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) UNIQUE NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        db.commit()

    def get_applied_migrations(self, db: Session):
        return {row[0] for row in db.execute(text("SELECT filename FROM _migrations")).fetchall()}

    def run_migrations(self):
        """Execute all pending migrations."""
        if not os.path.exists(self.migration_dir):
            logger.warning(f"⚠️ Migration directory not found: {self.migration_dir}")
            return

        db = SessionLocal()
        try:
            self._ensure_migration_table(db)
            applied = self.get_applied_migrations(db)
            
            # List and sort files
            files = sorted([f for f in os.listdir(self.migration_dir) if f.endswith(".sql")])
            
            for f in files:
                if f in applied:
                    continue
                
                logger.info(f"🔄 Applying migration: {f}...")
                file_path = os.path.join(self.migration_dir, f)
                
                with open(file_path, "r", encoding="utf-8") as sql_file:
                    sql_script = sql_file.read()
                    
                # Execute
                # Note: sqlalchemy execute can handle multiple statements if driver allows, 
                # but might need splitting by semicolon if strict. 
                # For postgres+psycopg2 usually fine if passed as one block or use explicit split.
                # Here we assume simple statements or block execution support.
                try:
                    db.execute(text(sql_script))
                    # Record success
                    db.execute(text("INSERT INTO _migrations (filename) VALUES (:fn)"), {"fn": f})
                    db.commit()
                    logger.info(f"✅ Migration applied: {f}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"❌ Migration failed: {f} - {e}")
                    raise e # Stop on failure
                    
        except Exception as e:
            logger.error(f"❌ Migration process failed: {e}")
        finally:
            db.close()

migration_manager = MigrationManager()
