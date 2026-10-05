from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.services import job_search_service, job_sources

NOW = datetime.now(timezone.utc)


def _mock_httpx(monkeypatch, payload=None, raises=None, content=None):
    class FakeResponse:
        def __init__(self):
            self.content = content or b""

        def raise_for_status(self):
            if raises:
                raise raises
            return None

        def json(self):
            return payload

    def fake_get(url, **kwargs):
        if raises:
            raise raises
        return FakeResponse()

    monkeypatch.setattr(httpx, "get", fake_get)


def test_fetch_remoteok_skips_legal_notice_and_parses_jobs(monkeypatch):
    payload = [
        {"legal": "notice"},  # non-dict-style entry with no position -> skipped
        {
            "position": "Senior Python Developer",
            "company": "Acme",
            "url": "/remote-jobs/123",
            "date": "Tue, 01 Oct 2026 10:00:00 GMT",
            "location": "Remote",
        },
        "just a string",  # fully non-dict -> skipped
    ]
    _mock_httpx(monkeypatch, payload=payload)

    jobs = job_sources.fetch_remoteok("python developer")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Senior Python Developer"
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["url"] == "https://remoteok.com/remote-jobs/123"
    assert jobs[0]["is_remote"] is True
    assert jobs[0]["source"] == "remoteok"
    assert jobs[0]["posted_at"] is not None


def test_fetch_remoteok_failure_returns_empty(monkeypatch):
    _mock_httpx(monkeypatch, raises=httpx.ConnectError("down"))
    assert job_sources.fetch_remoteok("python") == []


def test_fetch_remotive_parses_jobs(monkeypatch):
    payload = {
        "jobs": [
            {
                "title": "Backend Engineer",
                "company_name": "Acme",
                "url": "https://remotive.com/jobs/1",
                "candidate_required_location": "Worldwide",
                "job_type": "full_time",
                "publication_date": "2026-10-01T10:00:00",
            }
        ]
    }
    _mock_httpx(monkeypatch, payload=payload)

    jobs = job_sources.fetch_remotive("backend engineer")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Backend Engineer"
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["is_remote"] is True
    assert jobs[0]["source"] == "remotive"


def test_fetch_remotive_failure_returns_empty(monkeypatch):
    _mock_httpx(monkeypatch, raises=httpx.ConnectError("down"))
    assert job_sources.fetch_remotive("backend") == []


def test_fetch_arbeitnow_parses_jobs(monkeypatch):
    payload = {
        "data": [
            {
                "title": "Python Developer",
                "company_name": "Berlin GmbH",
                "url": "https://arbeitnow.com/jobs/2",
                "location": "Berlin, Germany",
                "remote": False,
                "job_types": ["full-time"],
                "created_at": int((NOW - timedelta(days=5)).timestamp()),
            }
        ]
    }
    _mock_httpx(monkeypatch, payload=payload)

    jobs = job_sources.fetch_arbeitnow("python")
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Berlin GmbH"
    assert jobs[0]["is_remote"] is False
    assert jobs[0]["job_type"] == "full-time"
    assert jobs[0]["posted_at"] is not None


def test_fetch_arbeitnow_failure_returns_empty(monkeypatch):
    _mock_httpx(monkeypatch, raises=httpx.ConnectError("down"))
    assert job_sources.fetch_arbeitnow("python") == []


def test_scrape_weworkremotely_parses_rss(monkeypatch):
    rss = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Acme Corp: Senior Python Developer</title>
        <link>https://weworkremotely.com/jobs/1</link>
        <pubDate>Tue, 01 Oct 2026 10:00:00 +0000</pubDate>
      </item>
      <item>
        <title>No company prefix role</title>
        <link>https://weworkremotely.com/jobs/2</link>
      </item>
      <item><title>Missing link</title></item>
    </channel></rss>"""
    _mock_httpx(monkeypatch, content=rss)

    jobs = job_sources.scrape_weworkremotely("python")
    assert len(jobs) == 2
    assert jobs[0]["company"] == "Acme Corp"
    assert jobs[0]["title"] == "Senior Python Developer"
    assert jobs[0]["is_remote"] is True
    assert jobs[1]["company"] == ""
    assert jobs[1]["title"] == "No company prefix role"


def test_scrape_weworkremotely_failure_returns_empty(monkeypatch):
    _mock_httpx(monkeypatch, raises=httpx.ConnectError("down"))
    assert job_sources.scrape_weworkremotely("python") == []


def test_matches_keyword():
    assert job_sources.matches_keyword("Senior Python Developer", "Acme", "python, fastapi")
    assert job_sources.matches_keyword("Django Backend Engineer", "Acme", "python, fastapi, django")
    assert not job_sources.matches_keyword("Data Analyst", "Acme", "python, fastapi")
    assert not job_sources.matches_keyword("Anything", "Acme", "ab")  # too-short keywords ignored


def test_is_expired():
    recent = {"posted_at": NOW - timedelta(days=10)}
    old = {"posted_at": NOW - timedelta(days=70)}
    no_date = {"posted_at": None}
    naive = {"posted_at": (NOW - timedelta(days=10)).replace(tzinfo=None)}

    assert not job_search_service.is_expired(recent)
    assert job_search_service.is_expired(old)
    assert job_search_service.is_expired(no_date)
    assert not job_search_service.is_expired(naive)  # naive datetimes handled as UTC


def test_determine_locality():
    remote = {"is_remote": True, "location": "Anywhere"}
    local = {"is_remote": False, "location": "Berlin, Germany"}
    foreign = {"is_remote": False, "location": "Paris, France"}
    no_location = {"is_remote": False, "location": None}

    assert job_search_service.determine_locality(remote, "Germany") == "remote"
    assert job_search_service.determine_locality(local, "Germany") == "local"
    assert job_search_service.determine_locality(foreign, "Germany") is None
    assert job_search_service.determine_locality(no_location, "Germany") is None


def test_job_fingerprint_stable_and_distinct():
    fp1 = job_search_service.job_fingerprint("Acme", "Dev", "https://x/1", NOW)
    fp2 = job_search_service.job_fingerprint("acme ", "dev", "HTTPS://x/1", NOW)  # normalized -> same
    fp3 = job_search_service.job_fingerprint("Acme", "Dev", "https://x/1", None)
    fp4 = job_search_service.job_fingerprint("Acme", "Dev", "https://x/1", NOW + timedelta(days=1))

    assert fp1 == fp2
    assert fp1 != fp3
    assert fp1 != fp4  # new posting date -> new fingerprint (reopened)
