import re
from uuid import UUID

import httpx

from app.core.logging import logger
from app.db import database_sync
from app.db.models import ApplicationAttempt, JobMatch, Resume, User
from app.services import ai_service, email_service, progress

HTTP_TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

LOGIN_WALLED_HOSTS = ("linkedin", "indeed", "upwork", "glassdoor", "ziprecruiter", "monster", "adzuna")


def _fetch_page(url: str) -> str:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT, follow_redirects=True)
        return resp.text if resp.status_code < 400 else ""
    except Exception as exc:
        logger.warning("apply_page_fetch_failed url=%s error=%s", url, type(exc).__name__)
        return ""


def detect_apply_mechanism(page_html: str, url: str = "") -> dict:
    """Classify the posting page's apply path."""
    page = page_html.lower()
    url_l = url.lower()

    if any(h in url_l for h in LOGIN_WALLED_HOSTS):
        return {"type": "login_required"}
    if "sign in to continue" in page or "log in to apply" in page:
        return {"type": "login_required"}

    mailto = re.search(r"mailto:([\w\.\-\+%']+@[\w\.\-]+)", page_html)
    if mailto:
        email = mailto.group(1).split("?")[0].strip().strip("'")
        if "@" in email and "." in email.split("@")[-1]:
            return {"type": "mailto", "email": email}

    if re.search(r"<form[^>]*(apply|application|jobs?[-_]?careers?)", page):
        return {"type": "form"}
    if "application form" in page or "apply for this job" in page or "apply now" in page:
        return {"type": "form"}

    return {"type": "none"}


def _latest_resume(user_id) -> Resume | None:
    from sqlalchemy import select

    with database_sync.SyncSessionLocal() as session:
        result = session.execute(
            select(Resume)
            .where(Resume.user_id == user_id, Resume.is_current.is_(True))
            .order_by(Resume.created_at.desc())
        )
        return result.scalars().first()


def run_application(attempt_id: str) -> dict:
    """Full auto-apply pipeline. Sync session — the Celery task and the tests
    both run this; tests redirect the session factory to the test DB."""
    with database_sync.SyncSessionLocal() as session:
        attempt = session.get(ApplicationAttempt, UUID(attempt_id))
        if not attempt:
            logger.warning("apply_attempt_not_found attempt_id=%s", attempt_id)
            return {"status": "not_found"}

        user = session.get(User, attempt.user_id)
        match = session.get(JobMatch, attempt.job_match_id)
        if not user or not match:
            attempt.status = "failed"
            attempt.detail = "Job or user not found"
            session.commit()
            return {"status": "failed"}

        attempt.status = "running"
        session.commit()
        progress.publish_progress(str(user.id), "auto_apply", "started", match.title[:40])

        try:
            page = _fetch_page(match.url)
            mechanism = detect_apply_mechanism(page, url=match.url)
            logger.info("apply_mechanism attempt=%s mechanism=%s", attempt.id, mechanism.get("type"))

            if mechanism["type"] in ("login_required", "none"):
                attempt.status = "manual_required"
                attempt.detail = (
                    "This site requires a login — apply directly at the job link"
                    if mechanism["type"] == "login_required"
                    else "No automatic apply path detected — apply at the job link"
                )

            elif mechanism["type"] == "mailto":
                letter = _generate_cover_letter(user, match, page)
                attempt.cover_letter = letter
                sent = _send_application(match, user, letter, to_email=mechanism["email"])
                if sent:
                    attempt.status = "applied"
                    attempt.detail = f"Cover-letter email sent to {mechanism['email']}"
                    match.status = "applied"
                else:
                    attempt.status = "failed"
                    attempt.detail = "Email could not be sent (SMTP error)"

            else:  # "form" — Playwright auto-submit is Step 9
                letter = _generate_cover_letter(user, match, page)
                attempt.cover_letter = letter
                attempt.status = "manual_required"
                attempt.detail = (
                    "Auto-submitting web forms is Phase 2 — your tailored cover letter is ready to paste "
                    f"at {match.url}"
                )

            session.commit()

        except Exception as exc:
            session.rollback()
            logger.exception("apply_task_failed attempt=%s", attempt_id)
            attempt.status = "failed"
            attempt.detail = str(exc)[:400]
            session.commit()

        progress.publish_progress(
            str(user.id),
            "auto_apply",
            "completed" if attempt.status == "applied" else ("failed" if attempt.status == "failed" else "manual_required"),
            (attempt.detail or attempt.status)[:120],
        )
        return {"status": attempt.status, "detail": attempt.detail}


def _generate_cover_letter(user: User, match: JobMatch, page_html: str) -> str:
    latest = _latest_resume(user.id)
    resume_text = (latest.converted_text or "").strip() if latest else ""
    if not resume_text:
        resume_text = "(resume text unavailable)"
    return ai_service.build_cover_letter(
        resume_text=resume_text,
        job_title=match.title,
        job_text=page_html,
        candidate_country=user.country,
    )


def _send_application(match: JobMatch, user: User, cover_letter: str, to_email: str) -> bool:
    latest = _latest_resume(user.id)
    try:
        return email_service._send_app_sync(
            to_address=to_email,
            subject=f"Application — {match.title}",
            body=cover_letter,
            pdf_path=latest.pdf_path if latest else "",
            reply_to=user.email,
        )
    except Exception as exc:
        logger.warning("application_email_failed attempt_user=%s error=%s", user.id, exc)
        return False
