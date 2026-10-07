import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models import ApplicationAttempt, JobMatch, User
from app.services import ai_service, apply_service, progress
from app.workers import tasks as worker_tasks
from tests.conftest import auth_headers

NOW = datetime.now(timezone.utc)

POSTING_WITH_MAILTO = """
<html><body>
<h1>Backend Engineer</h1>
<a href="mailto:careers@zycto.com">Apply via email</a>
</body></html>
"""

POSTING_LINKEDIN = """
<html><body><h1>Acme</h1><p>Sign in to view this job posting</p></body></html>
"""

POSTING_PLAIN = """
<html><body>
<h1>Backend Engineer</h1>
<p>We are looking for engineers.</p>
</body></html>
"""

POSTING_FORM = """
<html><body>
<form id="job-application" action="/apply">
  <input type="text" name="name"/>
  <input type="email" name="email"/>
</form>
</body></html>
"""


async def _make_available_match(ctx, user_id, url="https://careers.example/jobs/1", title="Backend Engineer"):
    async with ctx.session_factory() as session:
        match = JobMatch(
            user_id=user_id,
            title=title,
            company="Acme",
            url=url,
            source="web",
            locality="local",
            is_remote=False,
            location="Rwanda",
            posted_at=NOW,
            fingerprint=uuid.uuid4().hex,
            status="available",
        )
        session.add(match)
        await session.commit()
        await session.refresh(match)
        return match


async def _get_user_id(ctx, email):
    async with ctx.session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one().id


async def test_apply_auto_mailto_sends_email_and_marks_applied(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    user_id = await _get_user_id(ctx, "user@test.com")
    match = await _make_available_match(ctx, user_id, url="https://careers.example/jobs/1")

    events = []
    monkeypatch.setattr(progress, "publish_progress", lambda uid, job, status, detail="": events.append((job, status, detail)))
    monkeypatch.setattr(apply_service, "_fetch_page", lambda url: POSTING_WITH_MAILTO)
    monkeypatch.setattr(ai_service, "build_cover_letter",
                        lambda resume_text, job_title, job_text, candidate_country: "Tailored letter")

    sent = {}

    from app.services import email_service

    def fake_send(to_address, subject, body, pdf_path, reply_to):
        sent.update(to=to_address, subject=subject, body=body, pdf_path=pdf_path, reply_to=reply_to)
        return True

    monkeypatch.setattr(email_service, "_send_app_sync", fake_send)

    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    assert resp.status_code == 202, resp.text
    attempt_id = resp.json()["attempt_id"]

    worker_tasks.apply_to_job.run(attempt_id)

    async with ctx.session_factory() as session:
        attempt = await session.get(ApplicationAttempt, uuid.UUID(attempt_id))
        match_row = await session.get(JobMatch, match.id)
        assert attempt.status == "applied"
        assert attempt.cover_letter == "Tailored letter"
        assert "careers@zycto.com" in attempt.detail
        assert match_row.status == "applied"
        assert match_row.apply_mechanism == "auto"

    assert sent["to"] == "careers@zycto.com"
    assert "Application — Backend Engineer" == sent["subject"]
    assert sent["body"] == "Tailored letter"
    assert sent["reply_to"] == "user@test.com"
    assert ("auto_apply", "started", "Backend Engineer") in events
    assert any(e[1] == "completed" for e in events if e[0] == "auto_apply")


async def test_apply_auto_login_walled(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    user_id = await _get_user_id(ctx, "user@test.com")
    match = await _make_available_match(ctx, user_id, url="https://www.linkedin.com/jobs/view/1")

    monkeypatch.setattr(progress, "publish_progress", lambda *a, **k: None)
    monkeypatch.setattr(apply_service, "_fetch_page", lambda url: POSTING_LINKEDIN)

    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    attempt_id = resp.json()["attempt_id"]
    worker_tasks.apply_to_job.run(attempt_id)

    async with ctx.session_factory() as session:
        attempt = await session.get(ApplicationAttempt, uuid.UUID(attempt_id))
        assert attempt.status == "manual_required"
        assert "login" in attempt.detail.lower()

    async with ctx.session_factory() as session:
        match_row = await session.get(JobMatch, match.id)
        assert match_row.status == "available"  # unchanged


async def test_apply_auto_plain_page_is_manual_required(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    user_id = await _get_user_id(ctx, "user@test.com")
    match = await _make_available_match(ctx, user_id, url="https://jobs.example/posting")

    monkeypatch.setattr(progress, "publish_progress", lambda *a, **k: None)
    monkeypatch.setattr(apply_service, "_fetch_page", lambda url: POSTING_PLAIN)

    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    attempt_id = resp.json()["attempt_id"]
    worker_tasks.apply_to_job.run(attempt_id)

    async with ctx.session_factory() as session:
        attempt = await session.get(ApplicationAttempt, uuid.UUID(attempt_id))
        assert attempt.status == "manual_required"
        assert "No automatic apply path" in attempt.detail


async def test_apply_auto_form_detected_stages_letter(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    user_id = await _get_user_id(ctx, "user@test.com")
    match = await _make_available_match(ctx, user_id, url="https://jobs.example/posting")

    monkeypatch.setattr(progress, "publish_progress", lambda *a, **k: None)
    monkeypatch.setattr(apply_service, "_fetch_page", lambda url: POSTING_FORM)
    monkeypatch.setattr(ai_service, "build_cover_letter",
                        lambda resume_text, job_title, job_text, candidate_country: "Tailored letter")

    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    attempt_id = resp.json()["attempt_id"]
    worker_tasks.apply_to_job.run(attempt_id)

    async with ctx.session_factory() as session:
        attempt = await session.get(ApplicationAttempt, uuid.UUID(attempt_id))
        assert attempt.status == "manual_required"
        assert attempt.cover_letter == "Tailored letter"
        assert "Phase 2" in attempt.detail


async def test_apply_auto_duplicate_returns_409(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    user_id = await _get_user_id(ctx, "user@test.com")
    match = await _make_available_match(ctx, user_id)

    monkeypatch.setattr(worker_tasks.apply_to_job, "delay", lambda aid: None)

    first = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    assert first.status_code == 202

    second = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    assert second.status_code == 409


async def test_apply_auto_already_applied_409(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    user_id = await _get_user_id(ctx, "user@test.com")
    match = await _make_available_match(ctx, user_id)

    async with ctx.session_factory() as session:
        row = await session.get(JobMatch, match.id)
        row.status = "applied"
        await session.commit()

    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    assert resp.status_code == 409


async def test_apply_auto_requires_auth(ctx):
    resp = await ctx.client.post(f"/jobs/matches/{uuid.uuid4()}/apply-auto")
    assert resp.status_code == 401


async def test_get_application_and_ownership(ctx, monkeypatch):
    headers = await auth_headers(ctx, email="alice@t.com")
    user_id = await _get_user_id(ctx, "alice@t.com")
    match = await _make_available_match(ctx, user_id)

    monkeypatch.setattr(worker_tasks.apply_to_job, "delay", lambda aid: None)
    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    assert resp.status_code == 202

    resp2 = await ctx.client.get(f"/jobs/matches/{match.id}/application", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "pending"

    # another user gets 404
    headers_b = await auth_headers(ctx, email="bob@t.com")
    resp3 = await ctx.client.get(f"/jobs/matches/{match.id}/application", headers=headers_b)
    assert resp3.status_code == 404


async def test_application_email_failure_marks_failed(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    user_id = await _get_user_id(ctx, "user@test.com")
    match = await _make_available_match(ctx, user_id)

    monkeypatch.setattr(progress, "publish_progress", lambda *a, **k: None)
    monkeypatch.setattr(apply_service, "_fetch_page", lambda url: POSTING_WITH_MAILTO)
    monkeypatch.setattr(ai_service, "build_cover_letter",
                        lambda resume_text, job_title, job_text, candidate_country: "Letter")

    from app.services import email_service

    monkeypatch.setattr(email_service, "_send_app_sync", lambda *a, **k: False)

    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    attempt_id = resp.json()["attempt_id"]
    worker_tasks.apply_to_job.run(attempt_id)

    async with ctx.session_factory() as session:
        attempt = await session.get(ApplicationAttempt, uuid.UUID(attempt_id))
        match_row = await session.get(JobMatch, match.id)
        assert attempt.status == "failed"
        assert match_row.status == "available"


async def test_matches_expose_apply_status(ctx, monkeypatch):
    headers = await auth_headers(ctx, email="stat@t.com")
    user_id = await _get_user_id(ctx, "stat@t.com")
    m_failed = await _make_available_match(ctx, user_id, url="https://a.example/j/1")
    m_plain = await _make_available_match(ctx, user_id, url="https://b.example/j/2")

    async with ctx.session_factory() as session:
        row = await session.get(JobMatch, m_failed.id)
        row.apply_mechanism = "auto"
        session.add(ApplicationAttempt(user_id=user_id, job_match_id=m_failed.id, status="failed"))
        await session.commit()

    resp = await ctx.client.get("/jobs/matches?status_filter=available", headers=headers)
    payload = {m["id"]: m for m in resp.json()}
    assert payload[str(m_failed.id)]["apply_status"] == "failed"
    assert payload[str(m_failed.id)]["apply_mechanism"] == "auto"
    assert payload[str(m_plain.id)]["apply_status"] is None


async def test_apply_auto_retries_after_failure(ctx, monkeypatch):
    headers = await auth_headers(ctx, email="retry@t.com")
    user_id = await _get_user_id(ctx, "retry@t.com")
    match = await _make_available_match(ctx, user_id)

    async with ctx.session_factory() as session:
        attempt = ApplicationAttempt(
            user_id=user_id, job_match_id=match.id, status="failed", detail="boom"
        )
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)
        attempt_id = attempt.id

    monkeypatch.setattr(worker_tasks.apply_to_job, "delay", lambda aid: None)
    resp = await ctx.client.post(f"/jobs/matches/{match.id}/apply-auto", headers=headers)
    assert resp.status_code == 202, resp.text
    assert resp.json()["attempt_id"] == str(attempt_id)

    async with ctx.session_factory() as session:
        rows = (await session.execute(
            select(ApplicationAttempt).where(ApplicationAttempt.job_match_id == match.id)
        )).scalars().all()
        assert len(rows) == 1  # reset, not duplicated
        assert rows[0].status == "pending"
        assert rows[0].detail is None
