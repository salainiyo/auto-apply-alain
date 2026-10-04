from app.services.resume_service import run_conversion
from app.services.role_service import extract_roles_for_resume
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
