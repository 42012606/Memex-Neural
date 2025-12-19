import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from sqlalchemy import or_
from src.core.database import SessionLocal
from src.models.chat import ChatMessage

def clean_hallucinations(dry_run=True):
    db = SessionLocal()
    try:
        # Keywords that indicate the specific "White Elephant" hallucination
        hallucination_keywords = [
            "李明", 
            "差旅报销单", 
            "张三", 
            "王强", 
            "行程单",
            "White Elephant", # In case it mentioned the effect itself in a weird way
        ]
        
        print(f"🔍 Scanning for hallucinations with keywords: {hallucination_keywords}")
        
        # Construct query
        conditions = [ChatMessage.content.like(f"%{kw}%") for kw in hallucination_keywords]
        query = db.query(ChatMessage).filter(or_(*conditions))
        
        messages = query.all()
        
        if not messages:
            print("✅ No hallucinated messages found.")
            return
            
        print(f"⚠️ Found {len(messages)} potentially hallucinated messages:")
        for msg in messages:
            print(f"  [ID: {msg.id}] Role: {msg.role} | Content: {msg.content[:50]}...")
            
        if dry_run:
            print("\n[DRY RUN] No changes made. Run with dry_run=False to execute cleaning.")
        else:
            print("\n🧹 Cleaning messages...")
            for msg in messages:
                # We replace strictly to preserve session history flow, rather than deleting
                msg.content = "[系统系统：此消息包含检测到的幻觉内容，已被自动清理]"
            
            db.commit()
            print(f"✅ Successfully cleaned {len(messages)} messages.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # check for --execute flag
    is_dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] == "--execute":
        is_dry_run = False
        
    clean_hallucinations(dry_run=is_dry_run)
