from uuid import UUID

from app.core.config import settings
from app.core.logging import logger
from app.db import database_sync
from app.db.models import Resume
from app.services import progress
from app.services.job_search_service import JOB_EXPIRY_DAYS, search_jobs_for_user as search_jobs_service
from app.services.role_service import extract_roles_for_resume
from app.services.resume_service import run_conversion
from app.workers.celery_app import celery_app

DASHBOARD_WINDOW_DAYS = 14  # Available -> Archived after 2 weeks unapplied


def _resume_owner(resume_id: str) -> str | None:
    try:
        with database_sync.SyncSessionLocal() as session:
            resume = session.get(Resume, UUID(resume_id))
            return str(resume.user_id) if resume else None
    except Exception:
        return None


@celery_app.task(
    name="app.workers.tasks.convert_resume_pdf",
    max_retries=3,
    default_retry_delay=10,
)
def convert_resume_pdf(resume_id: str) -> None:
    owner = _resume_owner(resume_id)
    if owner:
        progress.publish_progress(owner, "resume_conversion", "started")

    status = run_conversion(resume_id)

    if owner:
        if status == "completed":
            progress.publish_progress(owner, "resume_conversion", "completed", "Resume converted")
        else:
            progress.publish_progress(owner, "resume_conversion", "failed", status)

    if status == "completed":
        extract_roles_from_resume.delay(resume_id)


@celery_app.task(
    name="app.workers.tasks.extract_roles_from_resume",
    max_retries=3,
    default_retry_delay=10,
)
def extract_roles_from_resume(resume_id: str) -> None:
    owner = _resume_owner(resume_id)
    if owner:
        progress.publish_progress(owner, "role_extraction", "started")

    roles = extract_roles_for_resume(resume_id)

    if owner:
        if roles is None:
            progress.publish_progress(owner, "role_extraction", "failed", "Could not extract roles")
        else:
            progress.publish_progress(owner, "role_extraction", "completed", f"{len(roles)} roles")


@celery_app.task(name="app.workers.tasks.search_jobs_for_user")
def search_jobs_for_user(user_id: str) -> None:
    """Run a job search for one user.

    A fresh engine is created per invocation: asyncpg connections are bound to
    the event loop they were created in, and each celery run gets a new loop.
    """
    import asyncio

    progress.publish_progress(user_id, "job_search", "started")
    try:
        results = asyncio.run(_search(user_id))
        added = len(results) if results else 0
        progress.publish_progress(user_id, "job_search", "completed", f"{added} new matches")
    except Exception as exc:
        progress.publish_progress(user_id, "job_search", "failed", str(exc))
        raise

    # background pass: tell the user which jobs support auto-apply
    try:
        detect_apply_mechanisms.delay(user_id)
    except Exception as exc:
        logger.warning("mechanism_check_dispatch_failed user_id=%s error=%s", user_id, exc)


@celery_app.task(name="app.workers.tasks.detect_apply_mechanisms")
def detect_apply_mechanisms(user_id: str) -> None:
    """Check each new match's posting page for auto-apply support (mailto vs manual)."""
    from app.services.apply_service import detect_mechanisms_for_user

    progress.publish_progress(user_id, "mechanism_check", "started")
    try:
        checked = detect_mechanisms_for_user(user_id)
        progress.publish_progress(user_id, "mechanism_check", "completed", f"{checked} job pages checked")
    except Exception as exc:
        progress.publish_progress(user_id, "mechanism_check", "failed", str(exc))
        raise


async def _search(user_id: str):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            return await search_jobs_service(db, user_id)
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.tasks.run_periodic_job_search")
def run_periodic_job_search() -> None:
    """Beat task: search jobs for every verified user with a current resume."""
    import asyncio

    asyncio.run(_search_all_users())


async def _search_all_users():
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.db.models import Resume, User

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            result = await db.execute(
                select(User.id)
                .join(Resume, Resume.user_id == User.id)
                .where(User.is_verified.is_(True), Resume.is_current.is_(True))
            )
            user_ids = result.scalars().all()
    finally:
        await engine.dispose()

    for user_id in user_ids:
        try:
            search_jobs_for_user.delay(str(user_id))
        except Exception as exc:
            logger.warning("periodic_search_dispatch_failed user_id=%s error=%s", user_id, exc)


@celery_app.task(name="app.workers.tasks.archive_expired_matches")
def archive_expired_matches() -> None:
    """Beat task: move Available matches older than 14 days to Archived."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import and_, or_, update

    from app.db import database_sync
    from app.db.models import JobMatch

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DASHBOARD_WINDOW_DAYS)
    stale_cutoff = now - timedelta(days=JOB_EXPIRY_DAYS)

    with database_sync.SyncSessionLocal() as db:
        result = db.execute(
            update(JobMatch)
            .where(
                JobMatch.status == "available",
                or_(
                    JobMatch.created_at < cutoff,
                    and_(JobMatch.posted_at.is_not(None), JobMatch.posted_at < stale_cutoff),
                ),
            )
            .values(status="archived")
            .returning(JobMatch.id)
        )
        archived_ids = result.scalars().all()
        db.commit()

    if archived_ids:
        logger.info("matches_auto_archived count=%s", len(archived_ids))


@celery_app.task(name="app.workers.tasks.apply_to_job")
def apply_to_job(attempt_id: str) -> None:
    from app.services.apply_service import run_application

    run_application(attempt_id)
