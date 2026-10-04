import uuid
from pathlib import Path

import pdfplumber
from sqlalchemy import select

from app.db.models import Resume, User
from app.services import resume_service
from app.workers import tasks as worker_tasks
from tests.conftest import auth_headers

FAKE_PDF_CONTENT = b"%PDF-1.4\nFake pdf content for testing\n"


class FakePage:
    def extract_text(self):
        return "John Doe — Software Engineer\nSkills: Python, FastAPI, PostgreSQL"


class FakePdf:
    pages = [FakePage()]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


async def _upload(ctx, headers, filename="resume.pdf", content=FAKE_PDF_CONTENT, content_type="application/pdf"):
    return await ctx.client.post(
        "/resumes/upload",
        headers=headers,
        files={"file": (filename, content, content_type)},
    )


async def _get_user_id_by_email(ctx, email):
    async with ctx.session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one().id


async def test_upload_success(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    dispatched = []
    monkeypatch.setattr(
        worker_tasks.convert_resume_pdf, "delay", lambda rid: dispatched.append(rid)
    )

    resp = await _upload(ctx, headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["original_filename"] == "resume.pdf"
    assert data["status"] == "pending"
    assert data["is_current"] is True
    assert dispatched == [data["id"]]

    async with ctx.session_factory() as session:
        resume = await session.get(Resume, uuid.UUID(data["id"]))
        assert Path(resume.pdf_path).read_bytes() == FAKE_PDF_CONTENT


async def test_upload_requires_auth(ctx):
    resp = await ctx.client.post(
        "/resumes/upload",
        files={"file": ("resume.pdf", FAKE_PDF_CONTENT, "application/pdf")},
    )
    assert resp.status_code == 401


async def test_upload_rejects_non_pdf_filename(ctx):
    headers = await auth_headers(ctx)
    resp = await _upload(ctx, headers, filename="resume.txt")
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


async def test_upload_rejects_wrong_content_type(ctx):
    headers = await auth_headers(ctx)
    resp = await _upload(ctx, headers, content_type="text/plain")
    assert resp.status_code == 400
    assert "pdf" in resp.json()["detail"].lower()


async def test_upload_rejects_fake_pdf_magic_bytes(ctx):
    headers = await auth_headers(ctx)
    resp = await _upload(ctx, headers, content=b"not a pdf at all")
    assert resp.status_code == 400
    assert "invalid pdf" in resp.json()["detail"].lower()


async def test_upload_too_large(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)

    big = FAKE_PDF_CONTENT + b"\0" * (10 * 1024 * 1024 + 1)
    resp = await _upload(ctx, headers, content=big)
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()


async def test_conversion_completes(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)
    monkeypatch.setattr(pdfplumber, "open", lambda path: FakePdf())

    resp = await _upload(ctx, headers)
    resume_id = resp.json()["id"]

    resume_service.run_conversion(resume_id)

    async with ctx.session_factory() as session:
        resume = await session.get(Resume, uuid.UUID(resume_id))
        assert resume.status == "completed"
        assert resume.error is None
        assert resume.converted_path and resume.converted_path.endswith(".txt")
        assert "Software Engineer" in resume.converted_text
        assert Path(resume.converted_path).read_text(encoding="utf-8") == resume.converted_text


async def test_conversion_failure_marks_failed(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)

    def boom(path):
        raise ValueError("corrupt pdf")

    monkeypatch.setattr(pdfplumber, "open", boom)

    resp = await _upload(ctx, headers)
    resume_id = resp.json()["id"]

    resume_service.run_conversion(resume_id)

    async with ctx.session_factory() as session:
        resume = await session.get(Resume, uuid.UUID(resume_id))
        assert resume.status == "failed"
        assert "corrupt pdf" in resume.error


async def test_conversion_unknown_resume_is_noop(ctx):
    resume_service.run_conversion(str(uuid.uuid4()))


async def test_resume_replacement_retriggers_processing(ctx, monkeypatch):
    email = "alice@test.com"
    headers = await auth_headers(ctx, email=email)
    dispatched = []
    monkeypatch.setattr(
        worker_tasks.convert_resume_pdf, "delay", lambda rid: dispatched.append(rid)
    )

    first = await _upload(ctx, headers)
    second = await _upload(ctx, headers, filename="resume-v2.pdf")
    assert first.status_code == 201
    assert second.status_code == 201

    assert len(dispatched) == 2
    assert dispatched == [first.json()["id"], second.json()["id"]]

    user_id = await _get_user_id_by_email(ctx, email)
    async with ctx.session_factory() as session:
        resumes = (
            (
                await session.execute(
                    select(Resume).where(Resume.user_id == user_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(resumes) == 2
        by_id = {str(r.id): r for r in resumes}
        assert by_id[first.json()["id"]].is_current is False
        assert by_id[second.json()["id"]].is_current is True
        assert by_id[second.json()["id"]].original_filename == "resume-v2.pdf"


async def test_list_own_resumes_latest_first(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)

    await _upload(ctx, headers, filename="a.pdf")
    await _upload(ctx, headers, filename="b.pdf")

    resp = await ctx.client.get("/resumes", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0]["original_filename"] == "b.pdf"
    assert items[1]["original_filename"] == "a.pdf"


async def test_resumes_isolated_per_user(ctx, monkeypatch):
    headers_a = await auth_headers(ctx, email="alice@test.com")
    headers_b = await auth_headers(ctx, email="bob@test.com")
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)

    await _upload(ctx, headers_a, filename="alice.pdf")
    await _upload(ctx, headers_b, filename="bob.pdf")

    resp_a = await ctx.client.get("/resumes", headers=headers_a)
    resp_b = await ctx.client.get("/resumes", headers=headers_b)
    assert [i["original_filename"] for i in resp_a.json()] == ["alice.pdf"]
    assert [i["original_filename"] for i in resp_b.json()] == ["bob.pdf"]


async def test_get_current_resume(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    monkeypatch.setattr(worker_tasks.convert_resume_pdf, "delay", lambda rid: None)
    monkeypatch.setattr(pdfplumber, "open", lambda path: FakePdf())

    await _upload(ctx, headers, filename="my-resume.pdf")
    resp = await ctx.client.get("/resumes/current", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["original_filename"] == "my-resume.pdf"
    assert data["is_current"] is True


async def test_get_current_resume_none_uploaded(ctx):
    headers = await auth_headers(ctx)
    resp = await ctx.client.get("/resumes/current", headers=headers)
    assert resp.status_code == 404
    assert "no resume" in resp.json()["detail"].lower()
