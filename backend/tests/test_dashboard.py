from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db.models import JobMatch, User
from app.workers import tasks as worker_tasks
from tests.conftest import auth_headers


async def _make_match(ctx, user_id, status="available", age_days=0) -> JobMatch:
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    match = JobMatch(
        user_id=user_id,
        title=f"Role {uuid4().hex[:6]}",
        company="Acme",
        url=f"https://jobs.example/{uuid4().hex}",
        source="remotive",
        locality="remote",
        is_remote=True,
        posted_at=created,
        fingerprint=uuid4().hex,
        status=status,
    )
    async with ctx.session_factory() as session:
        session.add(match)
        await session.commit()
        await session.refresh(match)
        match_id = match.id
        # backdate created_at to simulate age
        if age_days:
            row = await session.get(JobMatch, match_id)
            row.created_at = created
            await session.commit()
    return match_id


async def _get_user_id(ctx, email):
    async with ctx.session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one().id


async def test_dashboard_summary_counts(ctx):
    headers = await auth_headers(ctx, email="dash@test.com")
    user_id = await _get_user_id(ctx, "dash@test.com")

    await _make_match(ctx, user_id, status="available")
    await _make_match(ctx, user_id, status="available")
    await _make_match(ctx, user_id, status="applied")
    await _make_match(ctx, user_id, status="archived")

    resp = await ctx.client.get("/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"available": 2, "applied": 1, "archived": 1}


async def test_dashboard_summary_empty(ctx):
    headers = await auth_headers(ctx, email="emptydash@test.com")
    resp = await ctx.client.get("/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"available": 0, "applied": 0, "archived": 0}


async def test_dashboard_summary_requires_auth(ctx):
    resp = await ctx.client.get("/dashboard/summary")
    assert resp.status_code == 401


async def test_pipeline_status_empty(ctx):
    headers = await auth_headers(ctx, email="pipe@test.com")
    resp = await ctx.client.get("/dashboard/status", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["resume_status"] == "none"
    assert data["roles_count"] == 0
    assert data["available"] == 0
    assert data["last_extraction_at"] is None
    assert data["last_search_at"] is None


async def test_pipeline_status_requires_auth(ctx):
    resp = await ctx.client.get("/dashboard/status")
    assert resp.status_code == 401


async def test_pipeline_status_reflects_matches(ctx):
    headers = await auth_headers(ctx, email="pipe2@test.com")
    user_id = await _get_user_id(ctx, "pipe2@test.com")
    await _make_match(ctx, user_id, status="available")
    await _make_match(ctx, user_id, status="applied")

    resp = await ctx.client.get("/dashboard/status", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] == 1
    assert data["applied"] == 1
    assert data["archived"] == 0
    assert data["resume_status"] == "none"


async def test_search_sets_last_search_at(ctx, monkeypatch):
    from app.services import ai_service, job_search_service, role_service
    from app.workers import tasks as worker_tasks
    from tests.conftest import DEFAULT_PASSWORD, DEFAULT_EMAIL

    email = DEFAULT_EMAIL
    headers = await auth_headers(ctx, email=email)

    import pdfplumber

    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)
    monkeypatch.setattr(
        pdfplumber,
        "open",
        lambda path: type(
            "F",
            (),
            {
                "__enter__": lambda s: s,
                "__exit__": lambda s, *a: False,
                "pages": [type("P", (), {"extract_text": lambda s: "dev resume"})()],
            },
        )(),
    )
    monkeypatch.setattr(
        ai_service,
        "call_gemini",
        lambda prompt: '{"roles": [{"title": "Backend Developer", "keywords": ["python", "backend"]}]}',
    )
    from app.services import job_sources

    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_web_local", lambda kw, country: [])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    resp = await ctx.client.post(
        "/resumes/upload",
        headers=headers,
        files={"file": ("r.pdf", b"%PDF-1.4\nx\n", "application/pdf")},
    )
    resume_id = resp.json()["id"]
    from app.services import resume_service

    assert resume_service.run_conversion(resume_id) == "completed"
    role_service.extract_roles_for_resume(resume_id)

    async with ctx.session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one()
        await job_search_service.search_jobs_for_user(session, user.id)

    resp = await ctx.client.get("/dashboard/status", headers=headers)
    data = resp.json()
    assert data["last_search_at"] is not None
    assert data["last_extraction_at"] is not None
    assert data["roles_count"] == 1


async def test_dashboard_summary_isolated_per_user(ctx):
    headers_a = await auth_headers(ctx, email="a@dash.com")
    headers_b = await auth_headers(ctx, email="b@dash.com")
    user_a = await _get_user_id(ctx, "a@dash.com")

    await _make_match(ctx, user_a, status="available", age_days=0)

    resp_a = await ctx.client.get("/dashboard/summary", headers=headers_a)
    resp_b = await ctx.client.get("/dashboard/summary", headers=headers_b)
    assert resp_a.json()["available"] == 1
    assert resp_b.json()["available"] == 0


async def test_auto_archive_after_14_days(ctx):
    headers = await auth_headers(ctx, email="arch@test.com")
    user_id = await _get_user_id(ctx, "arch@test.com")

    old_match = await _make_match(ctx, user_id, status="available", age_days=15)
    recent_match = await _make_match(ctx, user_id, status="available", age_days=2)

    worker_tasks.archive_expired_matches.run()

    async with ctx.session_factory() as session:
        old = await session.get(JobMatch, old_match)
        recent = await session.get(JobMatch, recent_match)
        assert old.status == "archived"
        assert recent.status == "available"


async def test_applied_and_archived_not_affected_by_auto_archive(ctx):
    headers = await auth_headers(ctx, email="keep@test.com")
    user_id = await _get_user_id(ctx, "keep@test.com")

    applied_old = await _make_match(ctx, user_id, status="applied", age_days=30)
    archived_old = await _make_match(ctx, user_id, status="archived", age_days=30)

    worker_tasks.archive_expired_matches.run()

    async with ctx.session_factory() as session:
        applied = await session.get(JobMatch, applied_old)
        archived = await session.get(JobMatch, archived_old)
        assert applied.status == "applied"  # applied stays applied
        assert archived.status == "archived"


async def test_auto_archive_empty_db_is_noop(ctx):
    worker_tasks.archive_expired_matches.run()


async def test_auto_archive_stale_posting_date(ctx):
    headers = await auth_headers(ctx, email="stale@test.com")
    user_id = await _get_user_id(ctx, "stale@test.com")

    recent_find = await _make_match(ctx, user_id, status="available", age_days=2)
    fresh = await _make_match(ctx, user_id, status="available", age_days=1)

    # the recent-find match was actually posted 45 days ago -> stale
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz

    async with ctx.session_factory() as session:
        row = await session.get(JobMatch, recent_find)
        row.posted_at = _dt.now(_tz.utc) - _td(days=45)
        await session.commit()

    worker_tasks.archive_expired_matches.run()

    async with ctx.session_factory() as session:
        stale = await session.get(JobMatch, recent_find)
        ok = await session.get(JobMatch, fresh)
        assert stale.status == "archived"   # stale posting date, not age-in-dashboard
        assert ok.status == "available"
