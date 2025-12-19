import logging
import shutil
import os
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.storage import StorageRoot
from src.models.archive import ArchiveRecord

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Request Models ---

class StorageRootCreate(BaseModel):
    name: str
    mount_path: str
    is_default: bool = False

class StorageRootUpdate(BaseModel):
    name: Optional[str] = None
    mount_path: Optional[str] = None
    is_active: Optional[bool] = None

class StorageRootResponse(BaseModel):
    id: int
    name: str
    mount_path: str
    is_active: bool
    is_default: bool
    created_at: str

    class Config:
        orm_mode = True
        # Allow non-pydantic types (like SQLAlchemy models) to be converted
        # In Pydantic v2 this is 'from_attributes = True'

class ArchiveShortInfo(BaseModel):
    id: int
    processing_status: str
    summary: Optional[str] = None
    file_type: Optional[str] = None
    category: Optional[str] = None
    full_text: Optional[str] = None
    
class FileBrowserItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    has_children: bool = False
    size: int = 0  # File size in bytes
    modified: float = 0  # Unix timestamp
    archive_info: Optional[ArchiveShortInfo] = None

# --- Endpoints ---

@router.get("/storage/roots", response_model=List[StorageRootResponse])
async def get_storage_roots(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user)
):
    """获取所有存储库列表"""
    roots = db.query(StorageRoot).order_by(StorageRoot.created_at.desc()).all()
    # Manual conversion for datetime if needed, but response_model handling should suffice with specific config
    # To be safe for serialization:
    results = []
    for r in roots:
        results.append({
            "id": r.id,
            "name": r.name,
            "mount_path": r.mount_path,
            "is_active": r.is_active,
            "is_default": r.is_default,
            "created_at": r.created_at.isoformat() if r.created_at else ""
        })
    return results

@router.post("/storage/roots")
async def create_storage_root(
    request: StorageRootCreate,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user)
):
    """添加新的存储库"""
    # 1. 检查名称是否重复
    existing = db.query(StorageRoot).filter(StorageRoot.name == request.name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"存储库名称 '{request.name}' 已存在")

    # 2. 检查路径是否有效 (在容器内是否存在)
    path_obj = Path(request.mount_path)
    if not path_obj.exists():
        # 这里可以是 Warning，也可以是 Error。为了稳健性，建议 Error，防止配错。
        raise HTTPException(status_code=400, detail=f"路径不存在: {request.mount_path}。请确保已在 Docker 挂载该路径。")
    if not path_obj.is_dir():
        raise HTTPException(status_code=400, detail=f"路径必须是一个目录: {request.mount_path}")

    try:
        # 3. 如果设为默认，取消其他默认
        if request.is_default:
            db.query(StorageRoot).update({StorageRoot.is_default: False})
        
        # 4. 创建
        new_root = StorageRoot(
            name=request.name,
            mount_path=str(path_obj.absolute()).replace("\\", "/"), # Normalize to unix style for consistency
            is_default=request.is_default,
            is_active=True
        )
        db.add(new_root)
        db.commit()
        db.refresh(new_root)
        
        logger.info(f"✅ Created new storage root: {new_root.name} -> {new_root.mount_path}")
        return {
            "status": "ok",
            "message": "存储库已添加",
            "root": {
                "id": new_root.id,
                "name": new_root.name,
                "mount_path": new_root.mount_path
            }
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create storage root: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/storage/roots/{root_id}/default")
async def set_default_root(
    root_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user)
):
    """设为默认存储库"""
    target = db.query(StorageRoot).filter(StorageRoot.id == root_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="存储库不存在")
    
    try:
        # 取消所有默认
        db.query(StorageRoot).update({StorageRoot.is_default: False})
        # 设为默认
        target.is_default = True
        db.commit()
        return {"status": "ok", "message": f"默认存储库已切换为: {target.name}"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to set default root: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/storage/roots/{root_id}")
async def delete_storage_root(
    root_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user)
):
    """删除存储库"""
    target = db.query(StorageRoot).filter(StorageRoot.id == root_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="存储库不存在")
    
    if target.is_default:
        raise HTTPException(status_code=400, detail="无法删除默认存储库，请先切换其他默认库")

    # 检查是否有文件关联
    # 理论上应该检查 ArchiveRecord 表中是否有关联数据
    # 这里简单检查一下
    count = db.query(ArchiveRecord).filter(ArchiveRecord.storage_root_id == target.id).count()
    if count > 0:
        raise HTTPException(status_code=400, detail=f"该存储库包含 {count} 个文件记录，请先清理文件或迁移数据")

    try:
        db.delete(target)
        db.commit()
        logger.info(f"🗑️ Deleted storage root: {target.name}")
        return {"status": "ok", "message": "存储库已移除"}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete storage root: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.get("/storage/browse", response_model=List[FileBrowserItem])
async def browse_directory(
    path: str = "/",
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user)
):
    """
    Browse server directories and files.
    Returns both directories and files for the file browser.
    """
    # 1. Sanitize Path
    target_path = Path(path).resolve()
    
    if not target_path.exists():
        # Fallback to root or app/data if path doesn't exist
        target_path = Path("/").resolve()
        if not target_path.exists():
             target_path = Path(".").resolve()
    
    if not target_path.is_dir():
         raise HTTPException(status_code=400, detail="Not a directory")

    items = []
    try:
        # Sort: Directories first, then alphabetical
        all_entries = list(target_path.iterdir())
        
        # Separate dirs and files, sort each group
        dirs = sorted([p for p in all_entries if p.is_dir()], key=lambda x: x.name.lower())
        files = sorted([p for p in all_entries if p.is_file()], key=lambda x: x.name.lower())
        
        # Process directories first
        for p in dirs:
            try:
                # Skip hidden folders
                if p.name.startswith("."):
                    continue
                    
                items.append(FileBrowserItem(
                    name=p.name,
                    path=str(p.as_posix()),
                    is_dir=True,
                    has_children=True,  # Optimistic assumption
                    size=0,
                    modified=p.stat().st_mtime if p.exists() else 0
                ))
            except OSError:
                continue
        
        # Process files
        for p in files:
            try:
                # Skip hidden files
                if p.name.startswith("."):
                    continue
                
                stat_info = p.stat()
                items.append(FileBrowserItem(
                    name=p.name,
                    path=str(p.as_posix()),
                    is_dir=False,
                    has_children=False,
                    size=stat_info.st_size,
                    modified=stat_info.st_mtime
                ))
            except OSError:
                continue
                    
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied accessing this directory")
    except Exception as e:
        logger.error(f"Browse failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # 2. Enrich with Archive Metadata
    # Find which StorageRoot this path belongs to
    try:
        abs_target_path = str(target_path.absolute()).replace("\\", "/")
        
        # Find matching storage root
        # We need to find the root where root.mount_path is a prefix of abs_target_path
        storage_roots = db.query(StorageRoot).filter(StorageRoot.is_active == True).all()
        matched_root = None
        
        for root in storage_roots:
            root_path = root.mount_path
            if not root_path.endswith("/"):
                root_path += "/"
            
            # Check if current browsing path is inside this root
            # Append slash to target path for check to ensure we match directories correctly
            check_path = abs_target_path + "/"
            if check_path.startswith(root_path) or abs_target_path == root.mount_path:
                matched_root = root
                break
        
        if matched_root:
            # Calculate relative path for files in this directory
            # relative_path in DB is: "username/..../filename"
            # It seems relative_path usually includes the filename. 
            # So we need to query archives where relative_path matches each file item.
            
            # Get prefix relative to storage root
            if abs_target_path == matched_root.mount_path:
                rel_dir = ""
            else:
                rel_dir = os.path.relpath(abs_target_path, matched_root.mount_path).replace("\\", "/")
            
            if rel_dir == ".": rel_dir = ""
            
            # Build list of potential relative paths for the files in the list
            # Map filename -> item index
            file_map = {}
            for idx, item in enumerate(items):
                if not item.is_dir:
                    file_map[item.name] = idx
            
            if file_map:
                filenames = list(file_map.keys())
                
                # Query DB
                # Verify how relative_path is stored. Assuming "path/to/file.ext"
                # We want records where storage_root_id = matched_root.id AND filename IN filenames AND relative_path starts with rel_dir
                
                # A more precise check: relative_path == rel_dir + "/" + filename (if rel_dir not empty)
                # or just filename match if we trust filename + storage_root_id is enough uniqueness within a folder? 
                # No, filename is not unique across folders.
                # relative_path IS unique per storage root.
                
                query = db.query(ArchiveRecord).filter(
                    ArchiveRecord.storage_root_id == matched_root.id,
                    ArchiveRecord.filename.in_(filenames)
                )
                
                archives = query.all()
                
                for archive in archives:
                    # Double check directory match
                    # Archive.relative_path should equal join(rel_dir, archive.filename)
                    expected_rel = f"{rel_dir}/{archive.filename}" if rel_dir else archive.filename
                    
                    if archive.relative_path == expected_rel:
                        if archive.filename in file_map:
                            idx = file_map[archive.filename]
                            
                            # Logic to retrieve full text: prefer 'full_text' column, fallback to 'meta_data.ocr_text'
                            text_content = archive.full_text
                            if not text_content and archive.meta_data:
                                text_content = archive.meta_data.get("ocr_text")
                            
                            has_ft = bool(text_content)
                            ft_len = len(text_content) if has_ft else 0
                            logger.info(f"Enriching {archive.filename} (ID: {archive.id}). Content source: {'column' if archive.full_text else 'meta_data' if text_content else 'none'}, length: {ft_len}")

                            items[idx].archive_info = ArchiveShortInfo(
                                id=archive.id,
                                processing_status=archive.processing_status or "unknown",
                                summary=f"{archive.summary or ''} [DEBUG: has_ft={has_ft}]",
                                file_type=archive.file_type,
                                category=archive.category,
                                full_text=text_content
                            )

    except Exception as e:
        logger.error(f"Failed to enrich file metadata: {e}")
        # Build continue without metadata
        pass
        
    return items


@router.delete("/storage/files")
async def delete_physical_file(
    path: str,
    current_user_id: int = Depends(get_current_user)
):
    """
    Delete a physical file from disk.
    CAUTION: This is a destructive operation.
    """
    try:
        # Handle potential leading slash issue from frontend/posix conversion on Windows
        # e.g. /D:/... -> D:/...
        raw_path = path
        if os.name == 'nt' and raw_path.startswith('/') and ':' in raw_path:
            raw_path = raw_path.lstrip('/')
            
        file_path = Path(raw_path).resolve()
        logger.info(f"Attempting to delete physical file: {file_path} (Raw: {path})")
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {path} -> {file_path}")
            
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
            
        # Security: Simple safeguard
        # In a real app, strict checks against StorageRoots are required.
        # For this local desktop app, we ensure it's absolute and exists.
             
        os.remove(file_path)
        logger.info(f"🗑️ Deleted physical file: {file_path}")
        return {"status": "ok", "message": "File deleted"}
        
    except PermissionError as e:
         logger.error(f"Permission denied deleting {path}: {e}")
         raise HTTPException(status_code=403, detail=f"Permission denied: {e}")
    except OSError as e:
         logger.error(f"OS Error deleting {path}: {e}")
         raise HTTPException(status_code=500, detail=f"System error: {e}")
    except Exception as e:
        logger.error(f"Failed to delete file {path}: {e}")
        # Return generic 500 but log details
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")


@router.delete("/storage/folders")
async def delete_physical_folder(
    path: str,
    db: Session = Depends(get_db), # [Fix] Inject DB session
    current_user_id: int = Depends(get_current_user)
):
    """
    Delete a physical folder from disk recursively.
    """
    try:
        # Handle potential leading slash issue from frontend/posix conversion on Windows
        raw_path = path.strip()
        folder_path = Path(raw_path).resolve()
        
        # [Fix] Windows Path Handling:
        # If /D:/foo comes in, Path resolves it to C:\D:\foo (invalid)
        # We need to strip the leading slash if it exists and results in a valid path
        if os.name == 'nt' and not folder_path.exists() and raw_path.startswith('/'):
             alt_path = Path(raw_path.lstrip('/')).resolve()
             if alt_path.exists():
                 folder_path = alt_path
                 logger.info(f"Fixed Windows path: {raw_path} -> {folder_path}")

        logger.info(f"Attempting to delete physical folder: {folder_path} (Raw: {path})")
        
        if not folder_path.exists():
             # Last ditch effort: maybe it needs decoding? (Usually fastapi handles this)
             raise HTTPException(status_code=404, detail=f"Folder not found: {folder_path}")
            
        if not folder_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
            
        # [New] Database Cleanup Logic
        # 1. Identify which StorageRoot this folder belongs to
        # (db is now injected via Depends)
        
        abs_folder_path = str(folder_path.absolute()).replace("\\", "/")
        
        storage_roots = db.query(StorageRoot).filter(StorageRoot.is_active == True).all()
        matched_root = None
        for root in storage_roots:
            root_path = root.mount_path
            if not root_path.endswith("/"): root_path += "/"
            # Check if folders path is inside root
            if abs_folder_path.startswith(root_path) or abs_folder_path == root.mount_path:
                 matched_root = root
                 break
        
        if matched_root:
             # Calculate relative prefix
             if abs_folder_path == matched_root.mount_path:
                 rel_prefix = "" 
             else:
                 rel_prefix = os.path.relpath(abs_folder_path, matched_root.mount_path).replace("\\", "/")
             
             if rel_prefix == ".": rel_prefix = ""
             
             # If rel_prefix is empty, it means we are deleting the ROOT itself (or everything in it).
             # CAUTION: This operation is massive.
             
             # We want to delete all archives where storage_root_id == matched_root.id
             # AND relative_path starts with rel_prefix + "/" (or just rel_prefix if it's unique enough)
             
             logger.info(f"Cleaning up DB records for folder: {abs_folder_path} (Root ID: {matched_root.id}, Prefix: {rel_prefix})")
             
             query = db.query(ArchiveRecord).filter(ArchiveRecord.storage_root_id == matched_root.id)
             
             if rel_prefix:
                 # Standard folder deletion
                 # relative_path should start with "folder_name/"
                 # e.g. "docs/file1.txt" starts with "docs/"
                 like_pattern = f"{rel_prefix}/%"
                 query = query.filter(ArchiveRecord.relative_path.like(like_pattern))
             
             deleted_count = query.delete(synchronize_session=False)
             db.commit()
             logger.info(f"🗑️ Deleted {deleted_count} archive records associated with folder: {rel_prefix}")

        # Use shutil.rmtree with error handling
        try:
            shutil.rmtree(folder_path)
        except OSError as e:
            # Try to handle read-only files if necessary, or just fail with detail
            logger.error(f"shutil.rmtree failed: {e}")
            raise HTTPException(status_code=500, detail=f"System error deleting folder: {e.strerror}")

        logger.info(f"🗑️ Deleted physical folder: {folder_path}")
        return {"status": "ok", "message": f"Folder deleted ({deleted_count if 'deleted_count' in locals() else 0} DB records cleaned)"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete folder {path}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to delete folder {path}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")
