from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import JobMatch, Resume, Role, User
from app.schemas.dashboard import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class PipelineStatus(BaseModel):
    resume_status: str  # none | pending | processing | completed | failed
    roles_count: int
    available: int
    applied: int
    archived: int
    last_extraction_at: datetime | None
    last_search_at: datetime | None


@router.get("/status", response_model=PipelineStatus)
async def pipeline_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == current_user.id, Resume.is_current.is_(True))
        .order_by(Resume.created_at.desc())
    )
    resume = result.scalars().first()

    roles_count = 0
    if resume:
        roles_result = await db.execute(
            select(func.count()).select_from(Role).where(Role.resume_id == resume.id)
        )
        roles_count = roles_result.scalar_one()

    match_result = await db.execute(
        select(JobMatch.status, func.count())
        .where(JobMatch.user_id == current_user.id)
        .group_by(JobMatch.status)
    )
    counts = {status_value: count for status_value, count in match_result.all()}

    return {
        "resume_status": resume.status if resume else "none",
        "roles_count": roles_count,
        "available": counts.get("available", 0),
        "applied": counts.get("applied", 0),
        "archived": counts.get("archived", 0),
        "last_extraction_at": current_user.last_extraction_at,
        "last_search_at": current_user.last_search_at,
    }


@router.get("/summary", response_model=DashboardSummary)
async def dashboard_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobMatch.status, func.count())
        .where(JobMatch.user_id == current_user.id)
        .group_by(JobMatch.status)
    )
    counts = {status_value: count for status_value, count in result.all()}
    return {
        "available": counts.get("available", 0),
        "applied": counts.get("applied", 0),
        "archived": counts.get("archived", 0),
    }
