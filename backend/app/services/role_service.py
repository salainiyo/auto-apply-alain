from uuid import UUID

from sqlalchemy import delete

from app.core.logging import logger
from app.db import database_sync
from app.db.models import Resume, Role, User
from app.services import ai_service


def extract_roles_for_resume(resume_id: str) -> list[dict] | None:
    """Run Gemini role extraction for a converted resume and save the roles.

    Returns the extracted roles, or None when nothing could be extracted.
    """
    try:
        with database_sync.SyncSessionLocal() as session:
            resume = session.get(Resume, UUID(resume_id))
            if not resume or not resume.converted_text:
                logger.warning("roles_extraction_no_resume resume_id=%s", resume_id)
                return None

            user = session.get(User, resume.user_id)
            if not user:
                return None

            roles = ai_service.extract_roles(resume.converted_text, user.country)

            session.execute(delete(Role).where(Role.resume_id == resume.id))
            for item in roles:
                session.add(
                    Role(
                        user_id=resume.user_id,
                        resume_id=resume.id,
                        title=item["title"],
                        keywords=", ".join(item["keywords"]),
                    )
                )
            session.commit()
            logger.info(
                "roles_saved resume_id=%s count=%s", resume_id, len(roles)
            )
            return roles
    except Exception as exc:
        logger.exception("roles_extraction_failed resume_id=%s error=%s", resume_id, exc)
        return None
