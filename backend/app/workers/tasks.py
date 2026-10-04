from app.core.logging import logger
from app.services.job_search_service import search_jobs_for_user as search_jobs_service
from app.services.role_service import extract_roles_for_resume
from app.services.resume_service import run_conversion
from app.workers.celery_app import celery_app


@celery_app.task(
    name="app.workers.tasks.convert_resume_pdf",
    max_retries=3,
    default_retry_delay=10,
)
def convert_resume_pdf(resume_id: str) -> None:
    status = run_conversion(resume_id)
    if status == "completed":
        extract_roles_from_resume.delay(resume_id)


@celery_app.task(
    name="app.workers.tasks.extract_roles_from_resume",
    max_retries=3,
    default_retry_delay=10,
)
def extract_roles_from_resume(resume_id: str) -> None:
    extract_roles_for_resume(resume_id)


@celery_app.task(name="app.workers.tasks.search_jobs_for_user")
def search_jobs_for_user(user_id: str) -> None:
    """Run a job search for one user (new event loop for Celery context)."""
    import asyncio

    asyncio.run(_search(user_id))


async def _search(user_id: str):
    from app.db.database import SessionLocal

    async with SessionLocal() as db:
        await search_jobs_service(db, user_id)


@celery_app.task(name="app.workers.tasks.run_periodic_job_search")
def run_periodic_job_search() -> None:
    """Beat task: search jobs for every verified user with a current resume."""
    import asyncio

    asyncio.run(_search_all_users())


async def _search_all_users():
    from sqlalchemy import select

    from app.db.database import SessionLocal
    from app.db.models import Resume, User

    async with SessionLocal() as db:
        result = await db.execute(
            select(User.id)
            .join(Resume, Resume.user_id == User.id)
            .where(User.is_verified.is_(True), Resume.is_current.is_(True))
        )
        user_ids = result.scalars().all()

    for user_id in user_ids:
        try:
            search_jobs_for_user.delay(str(user_id))
        except Exception as exc:
            logger.warning("periodic_search_dispatch_failed user_id=%s error=%s", user_id, exc)
