import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pdfplumber
from sqlalchemy import select

from app.db.models import JobMatch, User
from app.services import ai_service, job_sources, job_search_service, resume_service, role_service
from app.workers import tasks as worker_tasks
from tests.conftest import auth_headers

FAKE_PDF_CONTENT = b"%PDF-1.4\nFake pdf content for testing\n"
NOW = datetime.now(timezone.utc)

GEMINI_RAW = (
    '{"roles": ['
    '{"title": "Backend Developer", "keywords": ["python", "fastapi", "backend"]},'
    '{"title": "Software Engineering Internship", "keywords": ["internship", "python", "entry level"]}'
    "]}"
)


class FakePage:
    def extract_text(self):
        return "John Doe — Software Engineer\nSkills: Python, FastAPI"


class FakePdf:
    pages = [FakePage()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def listing(title, company, url, source="remotive", location=None, job_type=None, is_remote=False, posted_at=NOW):
    return {
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "source": source,
        "job_type": job_type,
        "is_remote": is_remote,
        "posted_at": posted_at,
    }


FAKE_REMOTE = listing(
    "Senior Python Developer", "Acme Corp", "https://jobs.example/1",
    location="Remote", is_remote=True, job_type="full-time",
)
FAKE_LOCAL = listing(
    "Python Backend Developer", "Berlin GmbH", "https://jobs.example/2",
    source="arbeitnow", location="Berlin, Germany", is_remote=False, job_type="full-time",
)
FAKE_FOREIGN = listing(
    "Python Data Analyst", "Paris SA", "https://jobs.example/3",
    source="arbeitnow", location="Paris, France", is_remote=False,
)


async def _setup_user_with_roles(ctx, monkeypatch, email="jobber@test.com", extract_roles=True):
    headers = await auth_headers(ctx, email=email)
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)
    monkeypatch.setattr(pdfplumber, "open", lambda path: FakePdf())
    monkeypatch.setattr(ai_service, "call_gemini", lambda prompt: GEMINI_RAW)

    resp = await ctx.client.post(
        "/resumes/upload",
        headers=headers,
        files={"file": ("resume.pdf", FAKE_PDF_CONTENT, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    resume_id = resp.json()["id"]

    assert resume_service.run_conversion(resume_id) == "completed"
    if extract_roles:
        role_service.extract_roles_for_resume(resume_id)

    async with ctx.session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()

    return headers, resume_id, user.id


async def _run_search(ctx, user_id):
    async with ctx.session_factory() as session:
        return await job_search_service.search_jobs_for_user(session, user_id)


async def test_search_creates_available_matches(ctx, monkeypatch):
    headers, resume_id, user_id = await _setup_user_with_roles(ctx, monkeypatch)
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [FAKE_REMOTE])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [FAKE_LOCAL])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    matches = await _run_search(ctx, user_id)
    assert len(matches) == 2
    assert {m.locality for m in matches} == {"remote", "local"}
    assert all(m.status == "available" for m in matches)
    assert all(m.fingerprint for m in matches)

    resp = await ctx.client.get("/jobs/matches", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert {j["locality"] for j in data} == {"remote", "local"}
    assert {j["source"] for j in data} == {"remotive", "arbeitnow"}


async def test_non_expired_filter(ctx, monkeypatch):
    _, _, user_id = await _setup_user_with_roles(ctx, monkeypatch)
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [
        listing("Python Developer", "Old Corp", "https://jobs.example/old",
                location="Hamburg, Germany", posted_at=NOW - timedelta(days=70)),
        listing("Python Developer", "NoDate Corp", "https://jobs.example/nodate",
                location="Munich, Germany", posted_at=None),
        listing("Python Developer", "Fresh Corp", "https://jobs.example/fresh",
                location="Munich, Germany", posted_at=NOW - timedelta(days=10)),
    ])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    matches = await _run_search(ctx, user_id)
    assert len(matches) == 1
    assert matches[0].company == "Fresh Corp"


async def test_locality_local_vs_remote_vs_foreign(ctx, monkeypatch):
    _, _, user_id = await _setup_user_with_roles(ctx, monkeypatch)
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [FAKE_LOCAL, FAKE_FOREIGN])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    matches = await _run_search(ctx, user_id)
    # FAKE_LOCAL (Germany) kept as local; FAKE_FOREIGN (France, on-site) skipped
    assert len(matches) == 1
    assert matches[0].locality == "local"


async def test_dedup_rerun_no_duplicates(ctx, monkeypatch):
    _, _, user_id = await _setup_user_with_roles(ctx, monkeypatch)
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [FAKE_REMOTE])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [FAKE_LOCAL])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    first = await _run_search(ctx, user_id)
    assert len(first) == 2

    second = await _run_search(ctx, user_id)
    assert second == []  # same jobs -> never re-presented

    async with ctx.session_factory() as session:
        total = len((await session.execute(select(JobMatch).where(JobMatch.user_id == user_id))).scalars().all())
    assert total == 2


async def test_reopened_position_reenters_available(ctx, monkeypatch):
    _, _, user_id = await _setup_user_with_roles(ctx, monkeypatch)
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [FAKE_REMOTE])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    first = await _run_search(ctx, user_id)
    assert len(first) == 1

    # same company/title/url but a NEW posting date -> reopened position
    reopened = listing(
        FAKE_REMOTE["title"], FAKE_REMOTE["company"], FAKE_REMOTE["url"],
        location="Remote", is_remote=True, posted_at=NOW + timedelta(days=1),
    )
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [reopened])

    second = await _run_search(ctx, user_id)
    assert len(second) == 1
    assert second[0].status == "available"
    assert second[0].fingerprint != first[0].fingerprint


async def test_applied_match_not_represented(ctx, monkeypatch):
    headers, _, user_id = await _setup_user_with_roles(ctx, monkeypatch)
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [FAKE_REMOTE])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    matches = await _run_search(ctx, user_id)
    match_id = matches[0].id

    resp = await ctx.client.post(f"/jobs/matches/{match_id}/apply", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"

    # rerun search: same job is not re-presented, applied status untouched
    second = await _run_search(ctx, user_id)
    assert second == []

    async with ctx.session_factory() as session:
        rows = (await session.execute(select(JobMatch).where(JobMatch.user_id == user_id))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "applied"


async def test_search_endpoint_dispatches(ctx, monkeypatch):
    headers, _, _ = await _setup_user_with_roles(ctx, monkeypatch)
    dispatched = []
    monkeypatch.setattr(worker_tasks.search_jobs_for_user, "delay", lambda uid: dispatched.append(uid))

    resp = await ctx.client.post("/jobs/search", headers=headers)
    assert resp.status_code == 202, resp.text
    assert len(dispatched) == 1


async def test_search_endpoint_requires_completed_resume(ctx, monkeypatch):
    headers, _, _ = await _setup_user_with_roles(ctx, monkeypatch, extract_roles=False)
    monkeypatch.setattr(worker_tasks.search_jobs_for_user, "delay", lambda uid: None)

    resp = await ctx.client.post("/jobs/search", headers=headers)
    assert resp.status_code == 404
    assert "no roles" in resp.json()["detail"].lower()


async def test_search_endpoint_requires_auth(ctx):
    resp = await ctx.client.post("/jobs/search")
    assert resp.status_code == 401


async def test_matches_endpoint_requires_auth(ctx):
    resp = await ctx.client.get("/jobs/matches")
    assert resp.status_code == 401


async def test_matches_endpoint_invalid_status(ctx):
    headers = await auth_headers(ctx, email="m@t.com")
    resp = await ctx.client.get("/jobs/matches?status_filter=bogus", headers=headers)
    assert resp.status_code == 400


async def test_apply_unknown_match(ctx):
    headers = await auth_headers(ctx, email="m@t.com")
    resp = await ctx.client.post(f"/jobs/matches/{uuid.uuid4()}/apply", headers=headers)
    assert resp.status_code == 404


async def test_apply_isolated_between_users(ctx, monkeypatch):
    headers_a, _, user_id = await _setup_user_with_roles(ctx, monkeypatch, email="alice@t.com")
    headers_b = await auth_headers(ctx, email="bob@t.com")
    monkeypatch.setattr(job_sources, "fetch_remotive", lambda kw: [FAKE_REMOTE])
    monkeypatch.setattr(job_sources, "fetch_remoteok", lambda kw: [])
    monkeypatch.setattr(job_sources, "fetch_arbeitnow", lambda kw: [])
    monkeypatch.setattr(job_sources, "scrape_weworkremotely", lambda kw: [])

    matches = await _run_search(ctx, user_id)
    match_id = matches[0].id

    # bob cannot apply to alice's match
    resp = await ctx.client.post(f"/jobs/matches/{match_id}/apply", headers=headers_b)
    assert resp.status_code == 404

    resp = await ctx.client.post(f"/jobs/matches/{match_id}/apply", headers=headers_a)
    assert resp.status_code == 200
