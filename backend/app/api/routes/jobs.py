from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.api.deps import get_current_user
from app.core.logging import logger
from app.db.database import get_db
from app.db.models import ApplicationAttempt, JobMatch, Resume, User
from app.middleware.rate_limit import rate_limit
from app.schemas.job import ApplicationResponse, JobMatchResponse
from app.services import job_search_service
from app.workers import tasks as worker_tasks

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/search",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60))],
)
async def search_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    resume = await job_search_service.get_current_resume(db, current_user.id)
    if not resume or resume.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed resume found. Upload a resume and wait for conversion to finish.",
        )

    roles = await job_search_service.get_roles_for_resume(db, resume.id)
    if not roles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No roles extracted yet. Run role extraction first (POST /roles/extract).",
        )

    worker_tasks.search_jobs_for_user.delay(str(current_user.id))
    logger.info("job_search_dispatched user_id=%s", current_user.id)
    return {"message": "Job search started. Check /jobs/matches shortly."}


@router.get("/matches", response_model=list[JobMatchResponse])
async def list_matches(
    status_filter: str = "available",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if status_filter not in ("available", "applied", "archived"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be one of: available, applied, archived",
        )

    # local jobs first, then remote; newest first within each group
    locality_rank = case((JobMatch.locality == "local", 0), else_=1)
    result = await db.execute(
        select(JobMatch)
        .where(JobMatch.user_id == current_user.id, JobMatch.status == status_filter)
        .order_by(locality_rank, JobMatch.created_at.desc())
    )
    return result.scalars().all()


@router.post("/matches/{match_id}/apply", response_model=JobMatchResponse)
async def apply_to_match(
    match_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    match = await db.get(JobMatch, match_id)
    if not match or match.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job match not found"
        )

    match.status = "applied"
    await db.commit()
    await db.refresh(match)
    logger.info("job_applied user_id=%s match_id=%s", current_user.id, match.id)
    return match


@router.post(
    "/matches/{match_id}/apply-auto",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit(limit=5, window_seconds=60))],
)
async def apply_auto(
    match_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    match = await db.get(JobMatch, match_id)
    if not match or match.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job match not found")

    if match.status == "applied":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already applied to this match")

    existing = await db.execute(
        select(ApplicationAttempt).where(ApplicationAttempt.job_match_id == match_id)
    )
    existing_attempt = existing.scalars().first()
    if existing_attempt is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Application attempt already exists with status '{existing_attempt.status}'",
        )

    attempt = ApplicationAttempt(user_id=current_user.id, job_match_id=match_id, status="pending")
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    worker_tasks.apply_to_job.delay(str(attempt.id))
    logger.info("apply_auto_dispatched user_id=%s match_id=%s attempt_id=%s", current_user.id, match_id, attempt.id)
    return {"message": "Auto-apply queued", "attempt_id": str(attempt.id)}


@router.get("/matches/{match_id}/application", response_model=ApplicationResponse)
async def get_application(
    match_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    match = await db.get(JobMatch, match_id)
    if not match or match.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job match not found")

    result = await db.execute(
        select(ApplicationAttempt).where(ApplicationAttempt.job_match_id == match_id)
    )
    attempt = result.scalars().first()
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No application attempt yet")
    return attempt
