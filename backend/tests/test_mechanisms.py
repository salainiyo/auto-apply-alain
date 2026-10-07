import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models import JobMatch
from app.services import apply_service, progress
from app.workers import tasks as worker_tasks
from tests.conftest import auth_headers

NOW = datetime.now(timezone.utc)

PAGE_MAILTO = '<html><body><a href="mailto:jobs@example.com">Apply</a></body></html>'
PAGE_LINKEDIN = "<html><body>Sign in to continue</body></html>"


async def _make_match(ctx, user_id, url="https://example.com/job/1", status="available"):
    async with ctx.session_factory() as session:
        match = JobMatch(
            user_id=user_id,
            title="Backend Engineer",
            company="Acme",
            url=url,
            source="web",
            locality="local",
            is_remote=False,
            location="Rwanda",
            posted_at=NOW,
            fingerprint=uuid.uuid4().hex,
            status=status,
        )
        session.add(match)
        await session.commit()
        await session.refresh(match)
        return match


async def _user_id(ctx, email="user@test.com"):
    from app.db.models import User

    async with ctx.session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one().id


async def test_matches_expose_apply_mechanism(ctx):
    headers = await auth_headers(ctx)
    user_id = await _user_id(ctx)
    match = await _make_match(ctx, user_id)

    resp = await ctx.client.get("/jobs/matches?status_filter=available", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert any(m["id"] == str(match.id) and m["apply_mechanism"] == "unknown" for m in payload)


async def test_detect_mechanisms_updates_matches(ctx, monkeypatch):
    await auth_headers(ctx)  # registers the default user
    user_id = await _user_id(ctx)
    m1 = await _make_match(ctx, user_id, url="https://a.example/job/1")
    m2 = await _make_match(ctx, user_id, url="https://www.linkedin.com/jobs/view/2")
    m3 = await _make_match(ctx, user_id, url="https://b.example/job/3", status="applied")

    pages = {
        "https://a.example/job/1": PAGE_MAILTO,
        "https://www.linkedin.com/jobs/view/2": PAGE_LINKEDIN,
    }
    monkeypatch.setattr(apply_service, "_fetch_page", lambda url: pages.get(url, ""))

    checked = apply_service.detect_mechanisms_for_user(user_id)
    assert checked == 2  # applied match skipped

    async with ctx.session_factory() as session:
        assert (await session.get(JobMatch, m1.id)).apply_mechanism == "auto"
        assert (await session.get(JobMatch, m2.id)).apply_mechanism == "login_required"
        assert (await session.get(JobMatch, m3.id)).apply_mechanism == "unknown"


async def test_detect_mechanisms_fetch_failure_leaves_unknown(ctx, monkeypatch):
    await auth_headers(ctx)  # registers the default user
    user_id = await _user_id(ctx)
    match = await _make_match(ctx, user_id, url="https://flaky.example/job")

    monkeypatch.setattr(apply_service, "_fetch_page", lambda url: "")
    checked = apply_service.detect_mechanisms_for_user(user_id)
    assert checked == 0

    async with ctx.session_factory() as session:
        assert (await session.get(JobMatch, match.id)).apply_mechanism == "unknown"


async def test_detect_task_publishes_progress(ctx, monkeypatch):
    await auth_headers(ctx)  # registers the default user
    user_id = await _user_id(ctx)

    events = []
    monkeypatch.setattr(
        progress, "publish_progress", lambda uid, job, status, detail="": events.append((job, status, detail))
    )
    monkeypatch.setattr(apply_service, "detect_mechanisms_for_user", lambda uid: 5)

    worker_tasks.detect_apply_mechanisms.run(str(user_id))

    assert ("mechanism_check", "started", "") in events
    assert ("mechanism_check", "completed", "5 job pages checked") in events


def test_wellfound_is_login_walled():
    import re

    page = '<html><form id="apply"><input name="email"/></form></html>'
    assert apply_service.detect_apply_mechanism(page, url="https://wellfound.com/jobs/3068778")["type"] == "login_required"
    # a mailto wins over forms when the page exposes one
    assert apply_service.detect_apply_mechanism(PAGE_MAILTO, url="https://example.com/j")["type"] == "mailto"
