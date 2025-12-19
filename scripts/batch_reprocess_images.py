
import sys
import os
import asyncio
import logging
import argparse
from datetime import datetime

# Add src to path
sys.path.append(os.getcwd())

from src.core.database import SessionLocal
from src.models.archive import ArchiveRecord
from src.services.ai_service import AIService
from src.plugins.core_vectorizer import CoreVectorizerPlugin
from src.models.storage import StorageRoot

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ImageReprocessor")

async def process_images(limit: int = 10, force: bool = False, target_id: int = None):
    db = SessionLocal()
    try:
        query = db.query(ArchiveRecord).filter(
            ArchiveRecord.file_type.in_(["image", "Images"])
        )
        
        if target_id:
            query = query.filter(ArchiveRecord.id == target_id)
        
        # If not force, maybe only process those with missing full_text or old vectorization?
        # For this task, we want to upgrade ALL images to Parent-Child, 
        # but specifically those that need description refresh.
        # Let's assume we filter by those that haven't been re-processed recently/checked.
        # But for simplicity and the requirement "Fix historical data", we might iterate all.
        
        total = query.count()
        logger.info(f"🔍 Found {total} image archives.")
        
        archives = query.limit(limit).all()
        logger.info(f"🚀 Starting batch processing for {len(archives)} images...")
        
        ai_service = AIService()
        vectorizer = CoreVectorizerPlugin()
        
        success_count = 0
        
        for i, archive in enumerate(archives):
            logger.info(f"[{i+1}/{len(archives)}] Processing ID {archive.id}: {archive.filename}...")
            
            # 1. Check path
            file_path = archive.path
            if not file_path or not os.path.exists(file_path):
                # Try relative path with logic if needed, but archive.path property logic should handle it
                # If path property fails (e.g. storage root issue), manually construct?
                # Using archive.path from model which relies on storage_root
                if not file_path and archive.relative_path and archive.storage_root:
                     file_path = os.path.join(archive.storage_root.mount_path, archive.relative_path)

            if not file_path or not os.path.exists(file_path):
                 logger.warning(f"⚠️ File not found for ID {archive.id}: {file_path}. Skipping.")
                 continue

            # 2. Re-generate Description (Vision)
            # Only if force=True or full_text is empty/short
            # The goal says "Refresh Fulltext", so we should default to doing it unless it looks very new?
            # Let's do it.
            
            try:
                if force or not archive.full_text or len(archive.full_text) < 50:
                    logger.info("   📸 Generating new visual description...")
                    # We can execute strictly sync or async. AIService methods are sync but some models might slow.
                    # run_in_executor is safer.
                    description = await asyncio.to_thread(ai_service.recognize_image, file_path)
                    
                    if description:
                        archive.full_text = description
                        archive.processing_status = "completed"
                        # Update metadata to mark it as upgraded
                        if not archive.meta_data: archive.meta_data = {}
                        archive.meta_data["vision_model"] = "upgraded_v2"
                        archive.meta_data["last_processed"] = datetime.now().isoformat()
                        
                        db.commit()
                        logger.info("   ✅ Description updated.")
                    else:
                        logger.warning("   ⚠️ Failed to generate description (empty result).")
                else:
                    logger.info("   ℹ️ Skipping description generation (already exists).")

            except Exception as e:
                logger.error(f"   ❌ Vision API failed: {e}")
                # Continue to vectorization? Maybe description is enough if it existed.
            
            # 3. Re-Vectorize (Parent-Child Chunking)
            # CoreVectorizerPlugin now handles chunking automatically in _process_vectorization
            try:
                logger.info("   🧠 Re-vectorizing (Chunking)...")
                await vectorizer._process_vectorization(archive.id)
                success_count += 1
            except Exception as e:
                logger.error(f"   ❌ Vectorization failed: {e}")
                
        logger.info(f"🎉 Batch processing complete. Success: {success_count}/{len(archives)}")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch reprocess images for RAG upgrade.")
    parser.add_argument("--limit", type=int, default=10, help="Max number of images to process")
    parser.add_argument("--force", action="store_true", help="Force re-generation of descriptions even if present")
    parser.add_argument("--id", type=int, help="Target specific ID")
    
    args = parser.parse_args()
    
    asyncio.run(process_images(limit=args.limit, force=args.force, target_id=args.id))
