import logging
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.proposal import Proposal
from src.models.vector_node import VectorNode
from src.models.archive import ArchiveRecord

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Execute and approve a proposal.
    """
    proposal = db.query(Proposal).filter(
        Proposal.id == proposal_id,
        Proposal.status == "pending"
    ).first()

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already processed")

    # Security check: Ensure proposal belongs to user or system wide (if user_id is null)
    if proposal.user_id and proposal.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Not authorized to approve this proposal")

    try:
        if proposal.type == "refine_archive":
            _execute_refine_archive(proposal, db)
        else:
            # Add other types here
            logger.warning(f"Unknown proposal type: {proposal.type}")
        
        proposal.status = "approved"
        db.commit()
        
        return {"status": "success", "message": "Proposal approved and executed"}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to execute proposal {proposal_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")

@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: int,
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reject a proposal.
    """
    proposal = db.query(Proposal).filter(
        Proposal.id == proposal_id,
        Proposal.status == "pending"
    ).first()

    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found or already processed")
        
    if proposal.user_id and proposal.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Not authorized to reject this proposal")

    proposal.status = "rejected"
    db.commit()

    return {"status": "success", "message": "Proposal rejected"}

def _execute_refine_archive(proposal: Proposal, db: Session):
    """
    Logic for 'refine_archive' execution.
    Creates VectorNode entries from the proposal content.
    """
    content = proposal.content
    if not isinstance(content, dict):
        raise ValueError("Invalid proposal content format")

    archive_id = content.get("archive_id")
    suggested_nodes = content.get("suggested_nodes", [])

    if not archive_id or not suggested_nodes:
        raise ValueError("Missing archive_id or suggested_nodes in proposal content")

    # Verify archive exists
    archive = db.query(ArchiveRecord).filter(ArchiveRecord.id == archive_id).first()
    if not archive:
        raise ValueError(f"Archive {archive_id} not found")

    new_nodes_count = 0
    for node_data in suggested_nodes:
        # Expected node_data: { "chunk_index": 0, "content": "...", "meta": {} }
        new_node = VectorNode(
            parent_archive_id=archive_id,
            content=node_data.get("content", ""),
            chunk_index=node_data.get("chunk_index", 0),
            meta=node_data.get("meta", {})
        )
        db.add(new_node)
        new_nodes_count += 1
    
    # Optionally mark archive as processed/refined if there's a flag for it
    # archive.is_refined = True 
    
    logger.info(f"Created {new_nodes_count} VectorNodes for Archive {archive_id}")
