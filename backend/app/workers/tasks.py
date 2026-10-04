from app.services.resume_service import run_conversion
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.convert_resume_pdf", max_retries=3, default_retry_delay=10)
def convert_resume_pdf(resume_id: str) -> None:
    run_conversion(resume_id)
