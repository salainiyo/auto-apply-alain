import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

from app.core.logging import logger

HTTP_TIMEOUT = 30
USER_AGENT = "auto-apply-alain/0.1 (personal job search assistant)"

REMOTIVE_API = "https://remotive.com/api/remote-jobs"
REMOTEOK_API = "https://remoteok.com/api"
ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"
WEWORKREMOTELY_RSS = "https://weworkremotely.com/categories/remote-programming-jobs.rss"


def _parse_date(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(str(value))
    except (ValueError, TypeError):
        return None


def _listing(title, company, url, source, *, location=None, job_type=None, is_remote=False, posted_at=None):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip() or None,
        "url": (url or "").strip(),
        "source": source,
        "job_type": (job_type or "").strip() or None,
        "is_remote": bool(is_remote),
        "posted_at": _parse_date(posted_at),
    }


def fetch_remotive(keywords: str) -> list[dict]:
    try:
        resp = httpx.get(
            REMOTIVE_API,
            params={"search": keywords, "limit": 20},
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("job_source_failed source=remotive error=%s", exc)
        return []

    jobs = []
    for job in data.get("jobs", []) or []:
        jobs.append(
            _listing(
                title=job.get("title"),
                company=job.get("company_name"),
                url=job.get("url"),
                source="remotive",
                location=job.get("candidate_required_location"),
                job_type=job.get("job_type"),
                is_remote=True,
                posted_at=job.get("publication_date"),
            )
        )
    return jobs


def fetch_remoteok(keywords: str) -> list[dict]:
    try:
        resp = httpx.get(
            REMOTEOK_API,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("job_source_failed source=remoteok error=%s", exc)
        return []

    jobs = []
    for job in data or []:
        if not isinstance(job) or not job.get("position"):
            continue  # first element is a legal notice
        jobs.append(
            _listing(
                title=job.get("position"),
                company=job.get("company"),
                url=f"https://remoteok.com{job.get('url', '')}",
                source="remoteok",
                location=job.get("location"),
                job_type=None,
                is_remote=True,
                posted_at=job.get("date"),
            )
        )
    return jobs


def fetch_arbeitnow(keywords: str) -> list[dict]:
    try:
        resp = httpx.get(
            ARBEITNOW_API,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("job_source_failed source=arbeitnow error=%s", exc)
        return []

    jobs = []
    for job in data.get("data", []) or []:
        job_types = job.get("job_types") or []
        jobs.append(
            _listing(
                title=job.get("title"),
                company=job.get("company_name"),
                url=job.get("url"),
                source="arbeitnow",
                location=job.get("location"),
                job_type=", ".join(str(t) for t in job_types) or None,
                is_remote=bool(job.get("remote")),
                posted_at=job.get("created_at") or job.get("publication_date"),
            )
        )
    return jobs


def scrape_weworkremotely(keywords: str) -> list[dict]:
    """Scrape the public WeWorkRemotely RSS feed (respectful: public feed, rate-limited caller)."""
    try:
        resp = httpx.get(
            WEWORKREMOTELY_RSS,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.content)
    except Exception as exc:
        logger.warning("job_source_failed source=weworkremotely error=%s", exc)
        return []

    jobs = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if not title or not link:
            continue

        # WWR titles look like "Company: Job Title"
        company, role_title = "", title
        if ":" in title:
            company, role_title = (part.strip() for part in title.split(":", 1))

        jobs.append(
            _listing(
                title=role_title,
                company=company,
                url=link,
                source="weworkremotely",
                is_remote=True,
                posted_at=pub_date,
            )
        )
    return jobs


def matches_keyword(title: str, company: str, keywords: str) -> bool:
    """Keyword relevance check used by scrapers that cannot filter server-side."""
    haystack = f"{title} {company}".lower()
    words = re.findall(r"[a-z0-9+#.]+", keywords.lower())
    return any(word in haystack for word in words if len(word) > 2)
