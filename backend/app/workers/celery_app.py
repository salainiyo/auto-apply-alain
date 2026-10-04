from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "auto_apply",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # periodic job search: every 6 hours
    beat_schedule={
        "periodic-job-search": {
            "task": "app.workers.tasks.run_periodic_job_search",
            "schedule": crontab(minute=0, hour="*/6"),
        },
    },
)
