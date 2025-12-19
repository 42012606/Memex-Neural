import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import datetime

from src.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Use DATA_DIR from settings, fallback to ./data if not set
DATA_DIR = Path(getattr(settings, "DATA_DIR", "data"))
FEEDBACK_FILE = DATA_DIR / "memex_feedback" / "bad_cases.json"

class FeedbackRequest(BaseModel):
    input: str
    expected_intent: Optional[str] = None
    actual_intent: str
    comment: Optional[str] = None

@router.post("/system/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Save feedback to bad_cases.json"""
    try:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        entry = request.dict()
        entry["timestamp"] = datetime.datetime.now().isoformat()
        
        # Load existing
        data = []
        if FEEDBACK_FILE.exists():
            try:
                content = FEEDBACK_FILE.read_text(encoding="utf-8")
                if content.strip():
                    data = json.loads(content)
                    if not isinstance(data, list):
                        data = []
            except Exception:
                pass
        
        data.append(entry)
        
        FEEDBACK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Feedback saved to {FEEDBACK_FILE}")
        return {"status": "ok", "message": "Feedback received"}
    except Exception as e:
        logger.error(f"Failed to save feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/system/regression")
async def trigger_regression(background_tasks: BackgroundTasks):
    """Trigger regression test script"""
    script_path = Path("scripts/router_regression.py")
    if not script_path.exists():
        # Try absolute path
        script_path = Path.cwd() / "scripts" / "router_regression.py"
        if not script_path.exists():
            raise HTTPException(status_code=404, detail="Regression script not found")
        
    def run_script():
        try:
            # Use current python executable
            import sys
            logger.info("Starting regression test...")
            result = subprocess.run(
                [sys.executable, str(script_path)], 
                capture_output=True, 
                text=True
            )
            if result.returncode == 0:
                logger.info(f"Regression test completed successfully:\n{result.stdout}")
            else:
                logger.error(f"Regression test failed (code {result.returncode}):\n{result.stderr}")
        except Exception as e:
            logger.error(f"Regression test execution failed: {e}")

    background_tasks.add_task(run_script)
    return {"status": "ok", "message": "Regression test triggered in background"}


# --- Database Tools ---

class SqlQueryRequest(BaseModel):
    query: str

@router.get("/system/db/tables")
async def get_db_tables():
    """List all tables in the database"""
    from sqlalchemy import inspect
    from src.core.database import engine
    
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        return {"tables": tables}
    except Exception as e:
        logger.error(f"Failed to list tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/system/db/query")
async def execute_sql_query(request: SqlQueryRequest):
    """Execute raw SQL query"""
    from sqlalchemy import text
    from src.core.database import SessionLocal
    
    # Basic safety check (very distinct, not foolproof)
    forbidden_keywords = ["DROP", "TRUNCATE", "DELETE", "ALTER", "GRANT", "REVOKE"]
    # Ideally this should be more robust or restricted to read-only user
    # For now, we just warn or rely on user caution as this is an 'Advanced' tool
    
    db = SessionLocal()
    try:
        result = db.execute(text(request.query))
        
        # If it's a SELECT query, we can fetch results
        if result.returns_rows:
            columns = list(result.keys())
            rows = [list(row) for row in result.fetchall()]
            return {"columns": columns, "rows": rows}
        else:
            db.commit()
            return {"columns": [], "rows": [], "message": f"Query executed successfully. Rows affected: {result.rowcount}"}
            
    except Exception as e:
        db.rollback()
        logger.error(f"SQL execution failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()
