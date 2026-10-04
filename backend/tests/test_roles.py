import json
import uuid

import pdfplumber
from sqlalchemy import select

from app.db.models import Resume, Role, User
from app.services import ai_service, resume_service, role_service
from app.workers import tasks as worker_tasks
from tests.conftest import DEFAULT_COUNTRY, auth_headers

FAKE_PDF_CONTENT = b"%PDF-1.4\nFake pdf content for testing\n"

GEMINI_RAW_RESPONSE = json.dumps(
    {
        "roles": [
            {"title": "Backend Developer", "keywords": ["python", "fastapi", "backend"]},
            {"title": "Software Engineering Internship", "keywords": ["internship", "python", "entry level"]},
            {"title": "IT Apprenticeship", "keywords": ["apprenticeship", "it", "junior"]},
        ]
    }
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


async def _setup_user_with_converted_resume(
    ctx, monkeypatch, email="career@test.com", prompt_capture=None, run_extraction=True
):
    headers = await auth_headers(ctx, email=email)
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)
    monkeypatch.setattr(pdfplumber, "open", lambda path: FakePdf())
    monkeypatch.setattr(ai_service, "call_gemini", _make_fake_gemini(prompt_capture))

    resp = await ctx.client.post(
        "/resumes/upload",
        headers=headers,
        files={"file": ("resume.pdf", FAKE_PDF_CONTENT, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    resume_id = resp.json()["id"]

    status = resume_service.run_conversion(resume_id)
    assert status == "completed"
    if run_extraction:
        role_service.extract_roles_for_resume(resume_id)
    return headers, resume_id


def _make_fake_gemini(prompt_capture):
    def fake_gemini(prompt: str) -> str:
        if prompt_capture is not None:
            prompt_capture.append(prompt)
        return GEMINI_RAW_RESPONSE

    return fake_gemini


async def test_extraction_saves_roles_tied_to_resume(ctx, monkeypatch):
    prompt_capture: list[str] = []
    headers, resume_id = await _setup_user_with_converted_resume(
        ctx, monkeypatch, prompt_capture=prompt_capture
    )

    async with ctx.session_factory() as session:
        resume = await session.get(Resume, uuid.UUID(resume_id))
        roles = (
            (await session.execute(select(Role).where(Role.resume_id == resume.id)))
            .scalars()
            .all()
        )
        assert len(roles) == 3
        titles = {r.title for r in roles}
        assert "Backend Developer" in titles
        assert "Software Engineering Internship" in titles
        assert "IT Apprenticeship" in titles
        for role in roles:
            assert role.user_id == resume.user_id
            assert role.keywords

    resp = await ctx.client.get("/roles", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert data[0]["title"] == "Backend Developer"


async def test_prompt_includes_internship_apprenticeship_and_country(ctx, monkeypatch):
    prompt_capture: list[str] = []
    await _setup_user_with_converted_resume(ctx, monkeypatch, prompt_capture=prompt_capture)

    assert len(prompt_capture) == 1
    prompt = prompt_capture[0]
    assert "internship" in prompt.lower()
    assert "apprenticeship" in prompt.lower()
    assert DEFAULT_COUNTRY in prompt


async def test_reextraction_on_new_resume(ctx, monkeypatch):
    email = "career2@test.com"
    prompt_capture: list[str] = []
    headers, _ = await _setup_user_with_converted_resume(
        ctx, monkeypatch, email=email, prompt_capture=prompt_capture
    )

    # second upload → new resume → new extraction
    new_raw = json.dumps({"roles": [{"title": "DevOps Engineer", "keywords": ["docker", "kubernetes"]}]})
    monkeypatch.setattr(ai_service, "call_gemini", lambda prompt: new_raw)

    resp2 = await ctx.client.post(
        "/resumes/upload",
        headers=headers,
        files={"file": ("resume-v2.pdf", FAKE_PDF_CONTENT, "application/pdf")},
    )
    assert resp2.status_code == 201
    resume2_id = resp2.json()["id"]
    assert resume_service.run_conversion(resume2_id) == "completed"
    role_service.extract_roles_for_resume(resume2_id)

    # GET /roles returns roles of the CURRENT resume only
    resp = await ctx.client.get("/roles", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "DevOps Engineer"
    assert data[0]["resume_id"] == resume2_id

    # old resume's roles still exist in the DB, tied to the old resume
    async with ctx.session_factory() as session:
        resume1 = (
            (
                await session.execute(
                    select(Resume).where(
                        Resume.user_id == Resume.user_id, Resume.is_current.is_(False)
                    )
                )
            )
            .scalars()
            .first()
        )
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        old_resume = (
            (
                await session.execute(
                    select(Resume).where(
                        Resume.user_id == user.id, Resume.is_current.is_(False)
                    )
                )
            )
            .scalars()
            .first()
        )
        old_roles = (
            (await session.execute(select(Role).where(Role.resume_id == old_resume.id)))
            .scalars()
            .all()
        )
        assert len(old_roles) == 3
        assert resume1 is not None


async def test_manual_extract_endpoint_dispatches(ctx, monkeypatch):
    headers, resume_id = await _setup_user_with_converted_resume(ctx, monkeypatch)
    dispatched = []
    monkeypatch.setattr(
        worker_tasks.extract_roles_from_resume, "delay", lambda rid: dispatched.append(rid)
    )

    resp = await ctx.client.post("/roles/extract", headers=headers)
    assert resp.status_code == 202, resp.text
    assert dispatched == [resume_id]


async def test_manual_extract_without_completed_resume(ctx, monkeypatch):
    headers = await auth_headers(ctx, email="fresh@test.com")
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)

    resp = await ctx.client.post("/roles/extract", headers=headers)
    assert resp.status_code == 404
    assert "no completed resume" in resp.json()["detail"].lower()


async def test_roles_requires_auth(ctx):
    resp = await ctx.client.get("/roles")
    assert resp.status_code == 401


async def test_roles_empty_when_no_resume(ctx):
    headers = await auth_headers(ctx, email="empty@test.com")
    resp = await ctx.client.get("/roles", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_gemini_failure_does_not_crash_or_save(ctx, monkeypatch):
    headers, resume_id = await _setup_user_with_converted_resume(
        ctx, monkeypatch, run_extraction=False
    )

    def boom(prompt):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(ai_service, "call_gemini", boom)

    result = worker_tasks.extract_roles_from_resume.run(resume_id)
    assert result is None

    resp = await ctx.client.get("/roles", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_malformed_gemini_response_does_not_crash(ctx, monkeypatch):
    headers, resume_id = await _setup_user_with_converted_resume(
        ctx, monkeypatch, run_extraction=False
    )
    monkeypatch.setattr(ai_service, "call_gemini", lambda prompt: "not valid json")

    result = worker_tasks.extract_roles_from_resume.run(resume_id)
    assert result is None

    async with ctx.session_factory() as session:
        roles = (
            (
                await session.execute(
                    select(Role).where(Role.resume_id == uuid.UUID(resume_id))
                )
            )
            .scalars()
            .all()
        )
        assert roles == []


async def test_conversion_chains_extraction_task(ctx, monkeypatch):
    """Celery wrapper dispatches role extraction when conversion completes."""
    prompt_capture: list[str] = []
    headers, resume_id = await _setup_user_with_converted_resume(
        ctx, monkeypatch, prompt_capture=prompt_capture
    )

    dispatched = []
    monkeypatch.setattr(
        worker_tasks.extract_roles_from_resume, "delay", lambda rid: dispatched.append(rid)
    )

    # calling the celery wrapper directly (not the plain function)
    worker_tasks.convert_resume_pdf.run(resume_id)
    assert dispatched == [resume_id]
