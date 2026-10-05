import pdfplumber

from app.services import ai_service, progress, resume_service, role_service
from app.workers import tasks as worker_tasks
from tests.conftest import auth_headers

FAKE_PDF = b"%PDF-1.4\nx\n"

GEMINI_RAW = (
    '{"roles": ['
    '{"title": "Backend Developer", "keywords": ["python", "backend"]},'
    '{"title": "Frontend Developer", "keywords": ["react", "ui"]},'
    '{"title": "DevOps Engineer", "keywords": ["docker", "ci"]}'
    "]}"
)


class _FakePdf:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    class FakePage:
        def extract_text(self):
            return "dev resume"

    pages = [FakePage()]


async def test_convert_and_extract_tasks_publish_progress(ctx, monkeypatch):
    headers = await auth_headers(ctx)
    monkeypatch.setattr(worker_tasks.extract_roles_from_resume, "delay", lambda rid: None)
    monkeypatch.setattr(pdfplumber, "open", lambda path: _FakePdf())
    monkeypatch.setattr(ai_service, "call_gemini", lambda prompt: GEMINI_RAW)

    events = []
    monkeypatch.setattr(
        progress,
        "publish_progress",
        lambda uid, job, status, detail="": events.append((job, status, detail)),
    )

    resp = await ctx.client.post(
        "/resumes/upload",
        headers=headers,
        files={"file": ("r.pdf", b"%PDF-1.4\nx\n", "application/pdf")},
    )
    resume_id = resp.json()["id"]

    worker_tasks.convert_resume_pdf.run(resume_id)
    worker_tasks.extract_roles_from_resume.run(resume_id)

    jobs = [e[0] for e in events]
    assert jobs == ["resume_conversion", "resume_conversion", "role_extraction", "role_extraction"]
    assert events[0][1] == "started"
    assert events[1][1] == "completed"
    assert events[2][1] == "started"
    assert events[3][1] == "completed"
    assert "3 roles" in events[3][2]


def test_search_task_publishes_progress(monkeypatch):
    events = []
    monkeypatch.setattr(
        progress,
        "publish_progress",
        lambda uid, job, status, detail="": events.append((job, status, detail)),
    )

    async def fake_search(user_id: str):
        return []

    monkeypatch.setattr(worker_tasks, "_search", fake_search)

    worker_tasks.search_jobs_for_user.run("user-1")
    assert events == [("job_search", "started", ""), ("job_search", "completed", "0 new matches")]
