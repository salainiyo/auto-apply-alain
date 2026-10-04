from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.logging import logger
from app.db.database import get_db
from app.db.models import Resume, Role, User
from app.middleware.rate_limit import rate_limit
from app.schemas.role import RoleResponse
from app.workers import tasks as worker_tasks

router = APIRouter(prefix="/roles", tags=["roles"])


async def _get_current_resume(db: AsyncSession, user_id) -> Resume | None:
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user_id, Resume.is_current.is_(True))
        .order_by(Resume.created_at.desc())
    )
    return result.scalars().first()


@router.get("", response_model=list[RoleResponse])
async def list_roles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _get_current_resume(db, current_user.id)
    if not resume:
        return []

    result = await db.execute(
        select(Role).where(Role.resume_id == resume.id).order_by(Role.created_at.asc())
    )
    return result.scalars().all()


@router.post(
    "/extract",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60))],
)
async def extract_roles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await _get_current_resume(db, current_user.id)
    if not resume or resume.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed resume found. Upload a resume and wait for conversion to finish.",
        )

    worker_tasks.extract_roles_from_resume.delay(str(resume.id))
    logger.info("roles_extraction_dispatched user_id=%s resume_id=%s", current_user.id, resume.id)
    return {"message": "Role extraction started. Check /roles shortly."}
