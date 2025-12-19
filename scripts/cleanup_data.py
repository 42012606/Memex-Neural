
import sys
import os
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.core.database import SessionLocal
from src.models.archive import ArchiveRecord
from src.models.storage import StorageRoot
from src.models.chat import ChatMessage
from src.models.session import ChatSession
from src.models.user import User
from src.models.vector_node import VectorNode

# content-type: text/python

def cleanup_data():
    db = SessionLocal()
    try:
        print("--- Starting Data Cleanup ---")
        
        # 1. Clear Chat History
        print("Clearing Chat Messages...")
        try:
            db.query(ChatMessage).delete()
        except:
             pass
        
        print("Clearing Chat Sessions...")
        try:
            db.query(ChatSession).delete()
        except:
             pass
        
        # 1.5 Clear Vector Nodes
        print("Clearing Vector Nodes...")
        try:
            db.query(VectorNode).delete()
        except Exception as e:
            print(f"VectorNode clean error (info): {e}")

        # 2. Clear Archives (Knowledge Base)
        print("Clearing Archives...")
        db.query(ArchiveRecord).delete()


        # 3. Commit
        db.commit()
        print("--- Cleanup Database Success ---")
        
        # 4. Clear Physical Files
        print("Clearing Physical Files...")
        import shutil
        
        # Use project root relative path to ensure we hit the actual folder
        project_root = Path(__file__).parent.parent
        data_dir = project_root / "data"
        print(f"Target Data Directory: {data_dir.absolute()}")

        
        # 定义需要清理的目录 (User data directories)
        # 1. data/admin (Legacy/Simple mode)
        # 2. data/users/* (Multi-user mode)
        
        dirs_to_clean = []
        
        # Check data/admin
        admin_dir = data_dir / "admin"
        if admin_dir.exists():
            dirs_to_clean.append(admin_dir)
            
        # Check data/users
        users_dir = data_dir / "users"
        if users_dir.exists():
             for user_folder in users_dir.iterdir():
                 if user_folder.is_dir():
                     dirs_to_clean.append(user_folder)

        deleted_count = 0
        for d in dirs_to_clean:
            print(f"Scanning {d}...")
            # 遍历一级子目录 (e.g. 2025.12, _INBOX)
            for item in d.iterdir():
                # 跳过 logs 目录
                if item.name == "logs":
                    continue
                
                try:
                    if item.is_file():
                        item.unlink()
                        deleted_count += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                        deleted_count += 1
                        print(f"Removed directory: {item}")
                except Exception as e:
                    print(f"Failed to remove {item}: {e}")
                    
        print(f"--- Physical Cleanup Success: Removed {deleted_count} items ---")
        
    except Exception as e:
        print(f"Error during cleanup: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    import sys
    if "-y" in sys.argv:
        cleanup_data()
    else:
        confirm = input("This will delete ALL Content (Chats, Archives) but keep Users/Prompts. Type 'yes' to proceed: ")
        if confirm == "yes":
            cleanup_data()
        else:
            print("Cancelled.")
