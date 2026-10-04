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
