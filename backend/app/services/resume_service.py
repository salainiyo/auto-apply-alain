from pathlib import Path
from uuid import UUID

from app.core.logging import logger
from app.db import database_sync
from app.db.models import Resume
from app.services.pdf_converter import convert_pdf


def run_conversion(resume_id: str) -> str:
    """Convert a stored resume PDF to .txt and update its DB status.

    Plain function (no Celery) so it can be tested and reused directly.
    Returns the final status: "completed" or "failed".
    """
    with database_sync.SyncSessionLocal() as session:
        resume = session.get(Resume, UUID(resume_id))
        if not resume:
            logger.warning("conversion_resume_not_found resume_id=%s", resume_id)
            return "failed"

        resume.status = "processing"
        session.commit()

        try:
            txt_path, text_content = convert_pdf(Path(resume.pdf_path))
            resume.converted_path = str(txt_path)
            resume.converted_text = text_content
            resume.status = "completed"
            resume.error = None
        except Exception as exc:
            resume.status = "failed"
            resume.error = str(exc)
            logger.exception("conversion_failed resume_id=%s", resume_id)
        session.commit()
        return resume.status
