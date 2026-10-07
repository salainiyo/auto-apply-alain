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
    # periodic job search: every 6 hours; archive stale matches hourly
    beat_schedule={
        "periodic-job-search": {
            "task": "app.workers.tasks.run_periodic_job_search",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "archive-expired-matches": {
            "task": "app.workers.tasks.archive_expired_matches",
            "schedule": crontab(minute=20),  # hourly: keep Available strictly non-expired
        },
    },
)
