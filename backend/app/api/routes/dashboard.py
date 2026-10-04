from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.db.models import JobMatch, User
from app.schemas.dashboard import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


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
