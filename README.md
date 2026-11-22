# Job Freshness & Application Tracker

A full-stack application for tracking job applications and monitoring whether
job postings are still active, so applications only go to live roles.

## Features

- Application state tracking with status history and dashboard views.
- Job-source ingestion and posting-freshness checks.
- Resume upload, extraction and role suggestions via the Gemini API.
- Asynchronous background work with Celery and Redis.
- Email notifications, authentication and password recovery.
- Real-time progress events over WebSockets.

## Stack

- **Backend:** Python, FastAPI, SQLModel/SQLAlchemy, Alembic, Celery, Redis, PostgreSQL
- **Frontend:** JavaScript (Vite dev server)
- **Infrastructure:** Docker Compose
- **AI:** Gemini API for extracting roles and search keywords from resumes

## Architecture

```text
JavaScript frontend ──► FastAPI backend ──► PostgreSQL
                              │
                              ├──► Redis ──► Celery workers (jobs, email, AI)
                              └──► WebSocket progress events
```

The API is organized under `backend/app/api/routes/`, services under
`backend/app/services/`, background tasks under `backend/app/workers/`, and
models under `backend/app/db/models.py`.

## Quick start

```bash
cp .env.example .env
# fill in SECRET_KEY, database and SMTP settings, and GEMINI_API_KEY
docker compose up --build
```

Backend: `http://localhost:8000/docs`. Frontend: `http://localhost:5173`.

To run the backend locally without Docker:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

## Configuration

All settings come from `.env` (see `.env.example`). The example file contains
placeholders only — never commit populated credentials.

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY`, `JWT_ALGORITHM` | Token signing |
| `DATABASE_URL`, `DATABASE_SYNC_URL` | Async and sync database connections |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_URL` | Broker and result backend |
| `SMTP_*`, `EMAILS_FROM` | Verification and recovery email |
| `GEMINI_API_KEY` | Resume-to-role extraction |
| `FRONTEND_URL` | CORS and emailed links |

## Tests

```bash
cd backend && pytest -q
```

## Roadmap

- Add a CI workflow so test status is visible on the README.
- Broaden job-source coverage and freshness heuristics.
- Expand frontend coverage and end-to-end tests.

See [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). Licensed under [MIT](LICENSE).
