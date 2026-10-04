# auto-apply-alain — Project Plan

Web app (FastAPI backend + React frontend) that automates job applications: user uploads a resume, AI extracts suitable roles, the system searches for live jobs online, and the user applies from their dashboard.

**Workflow rule:** a step is written to this file **only after the user agrees on it**. New steps are appended the same way. Each step is implemented and tested before moving to the next.

**Status legend:** `[DONE]` approved by user, not yet implemented · `[DONE]` implemented + tests passing

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (async), Uvicorn |
| Database | PostgreSQL (asyncpg + SQLAlchemy 2.0 + Alembic migrations) |
| Password hashing | Argon2 (`argon2-cffi`) |
| Auth tokens | JWT (`PyJWT`) — access 30 min, refresh 7 days |
| AI | Google Gemini API (structured JSON output) |
| Rate limiting | Redis-backed, per-IP |
| Background tasks | Celery (Redis broker) + Celery Beat |
| Frontend | React + Vite |
| Logging | Structured JSON to **stdout only** (no log files — container/Docker friendly) |
| Config | `pydantic-settings` + `.env` (ALL secrets live in `.env`) |
| Testing | pytest + pytest-asyncio + httpx + pytest-cov, fakeredis, mocks for external services |

## Project Structure

```
auto-apply-alain/
├── PLAN.md
├── .env                     # ALL secrets (DB, Redis, JWT, SMTP, Gemini, job API keys)
├── docker-compose.yml       # postgres, redis, backend, celery worker, celery beat, frontend
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/            # config, security (argon2 + jwt), logging
│   │   ├── db/              # database, models (User, RevokedToken, Resume, Role, JobMatch)
│   │   ├── schemas/         # pydantic request/response models
│   │   ├── api/routes/      # auth.py, users.py, resumes.py, jobs.py, dashboard.py
│   │   ├── services/        # auth, email, ai, job search logic
│   │   ├── workers/         # celery tasks (pdf conversion, ai extraction, scraping)
│   │   └── middleware/      # rate limiting, request logging
│   └── tests/               # pytest suites per feature
└── frontend/                # React + Vite SPA
```

---

## Step 1 — Authentication System `[DONE]`

Full auth system: email/password only (Google OAuth **deferred for now** — personal project, can be re-added later), verified accounts only, JWT sessions, DB-backed logout blocklist, Redis rate limiting, stdout JSON logging.

### Routes
| Route | Purpose |
|---|---|
| `POST /auth/register` | email + password + **country (residence)** — argon2 hash, sends verification email, account inactive until verified |
| `POST /auth/verify-email` | consumes token from emailed link |
| `POST /auth/login` | returns access JWT (30 min) + refresh JWT (7 d); blocked for unverified accounts |
| `POST /auth/refresh` | new access token from refresh token |
| `POST /auth/logout` | token `jti` saved in `revoked_tokens` table (DB-backed blocklist) |
| `POST /auth/forgot-password` | issues + emails reset token |
| `POST /auth/reset-password` | consumes reset token, re-hashes password |
| `POST /auth/change-password` | requires current password, re-hashes |
| `GET /users/me` | protected route to verify auth works |

### Data models
- `User`: email, hashed_password, is_verified, **country** (no `auth_provider` until Google OAuth returns)
- `RevokedToken`: jti, expires_at (blocklist checked on every authenticated request)

### Cross-cutting
- **Rate limiting:** Redis-backed, per-IP; strictest on `login` and `forgot-password` (anti-brute-force)
- **Logging:** structured JSON to stdout only, request-logging middleware, auth event logging (no log files)

### Email
- Real SMTP via **Gmail app password** configured in `.env` — verification + password reset emails

---

## Step 2 — Project Setup `[DONE]`

- Restructure project into `backend/` + `frontend/` folders
- Create **public** GitHub repo: `auto-apply-alain`
- `docker-compose.yml`: postgres, redis, backend, celery worker, celery beat, frontend (+ test postgres)
- App must be **fully runnable and testable in development** before any deployment
- All sensitive info stays in `.env`

---

## Step 3 — Resume Upload `[DONE]`

- Logged-in user uploads resume — **PDF only** (non-PDF rejected)
- Celery task converts PDF → readable `.txt`/`.md` (async, never slows the app)
- Uploading a new resume or changing it re-triggers processing

---

## Step 4 — AI Role Extraction `[DONE]`

- Gemini reads the converted resume, extracts suggested apply-to roles (JSON structured output)
- Search scope explicitly includes **internships and apprenticeships** alongside full-time/contract
- Roles saved per user, tied to current resume; re-derived when resume is changed or replaced

---

## Step 5 — Job Search `[DONE]`

- Gemini roles used to search for jobs **online** — local or remote
- Search primarily based on user's **residence country**: `local` = job in user's country, `remote` = anywhere
- **Non-expired jobs only**
- Sources: **free job APIs** (Remotive, RemoteOK, Arbeitnow) + **scraping** selected boards (respecting robots.txt/ToS, rate-limited, run as Celery tasks; Beat for periodic re-search)
- **Dedup:** each match gets a fingerprint (company + title + source URL + posting date) stored per user in `job_matches`; a job already presented (any tab) is **never re-presented** unless it is a **reopened position** (new posting date → new fingerprint → re-enters Available)
- Found jobs presented on user dashboard with an **Apply** option

---

## Step 6 — Dashboard `[DONE]`

React + Vite dashboard with tabs:
- **Available** — jobs stay here for **14 days**; auto-moved to Archived if not applied within 2 weeks
- **Applied** — jobs the user applied for
- **Archived** — expired/unapplied after the 14-day window

---

## Testing — Every Route, Every Scenario `[DONE]`

**Stack:** pytest + pytest-asyncio + httpx + pytest-cov · dedicated test Postgres DB · fakeredis · mocked SMTP / Gemini / job APIs / scraper

Each step ships with its tests before moving on:

- **Auth:** register (success, duplicate email, invalid email, weak password, missing country), verify-email (valid, expired, invalid), login (success, wrong password, unverified, rate-limit trigger), refresh (valid, expired, revoked), logout (jti blocklisted in DB, already-revoked), forgot/reset/change password (full flow, wrong current password, invalid/expired reset token), `GET /users/me` (authenticated + unauthorized)
- **Resume upload:** PDF-only enforcement, successful upload → Celery conversion, replacement re-triggers processing
- **AI extraction:** Gemini mocked — extraction from sample resume, internship/apprenticeship inclusion, re-run on resume change
- **Job search:** mocked APIs/scraper — country-based locality, non-expired filter, internship/apprenticeship results, dedup (no re-presentation, reopened re-enters Available)
- **Dashboard:** Available (14-day window), Applied, Archived transitions
- **Celery tasks:** tested directly + end-to-end flows

---

## Prerequisites (user machine)

- Running PostgreSQL + Redis (local or Docker)
- Gemini API key (Google AI Studio)
- Gmail app password (SMTP emails)
- `gh` CLI authenticated (repo creation)
