"""
Dashboard API Endpoints
"""
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from src.core.database import get_db
from src.core.dependencies import get_current_user
from src.models.archive import ArchiveRecord, FileType
from src.models.proposal import Proposal

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/dashboard/stats", status_code=status.HTTP_200_OK)
async def get_dashboard_stats(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get dashboard statistics for the current user.
    Returns:
        - total_archives
        - vector_coverage (percentage)
        - pending_proposals_count
        - activity_30d (line chart data)
        - type_distribution (doughnut chart data)
    """
    # 1. Basic Stats
    total_archives = db.query(ArchiveRecord).filter(
        ArchiveRecord.user_id == current_user_id
    ).count()

    vectorized_count = db.query(ArchiveRecord).filter(
        ArchiveRecord.user_id == current_user_id,
        ArchiveRecord.is_vectorized == 1
    ).count()

    pending_proposals = db.query(Proposal).filter(
        Proposal.user_id == current_user_id,
        Proposal.status == "pending"
    ).count()

    vector_coverage = 0
    if total_archives > 0:
        vector_coverage = round((vectorized_count / total_archives) * 100, 1)

    # 2. Activity (Last 30 Days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    
    # Group by date
    activity_data = db.query(
        func.date(ArchiveRecord.processed_at).label("date"),
        func.count(ArchiveRecord.id).label("count")
    ).filter(
        ArchiveRecord.user_id == current_user_id,
        ArchiveRecord.processed_at >= thirty_days_ago
    ).group_by(
        func.date(ArchiveRecord.processed_at)
    ).order_by(
        func.date(ArchiveRecord.processed_at)
    ).all()

    # Fill in missing dates
    activity_map = {str(item.date): item.count for item in activity_data}
    chart_labels = []
    chart_data = []
    
    for i in range(30):
        date_cursor = thirty_days_ago + timedelta(days=i)
        date_str = date_cursor.strftime("%Y-%m-%d")
        chart_labels.append(date_str)
        chart_data.append(activity_map.get(date_str, 0))

    # 3. File Type Distribution
    type_data = db.query(
        ArchiveRecord.file_type,
        func.count(ArchiveRecord.id).label("count")
    ).filter(
        ArchiveRecord.user_id == current_user_id
    ).group_by(
        ArchiveRecord.file_type
    ).all()

    type_labels = [item.file_type for item in type_data]
    type_counts = [item.count for item in type_data]

    return {
        "summary": {
            "total_archives": total_archives,
            "vector_coverage": vector_coverage,
            "pending_proposals": pending_proposals
        },
        "charts": {
            "activity_30d": {
                "labels": chart_labels,
                "data": chart_data
            },
            "type_distribution": {
                "labels": type_labels,
                "data": type_counts
            }
        }
    }

@router.get("/dashboard/proposals", status_code=status.HTTP_200_OK)
async def get_pending_proposals(
    current_user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get list of pending proposals for the current user.
    """
    proposals = db.query(Proposal).filter(
        Proposal.user_id == current_user_id,
        Proposal.status == "pending"
    ).order_by(
        Proposal.created_at.desc()
    ).all()

    return [
        {
            "id": p.id,
            "type": p.type,
            "content": p.content,
            "reasoning": p.reasoning,
            "created_at": p.created_at
        }
        for p in proposals
    ]
