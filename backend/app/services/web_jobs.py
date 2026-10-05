"""Web job search — finds local jobs by searching the web.

Google blocks scrapers (captcha/consent), so DuckDuckGo's HTML endpoint is
used instead. Results are filtered toward recognizable job pages, each
listing page is fetched to extract the REAL posting date (JSON-LD or
human-readable formats), and anything without a fresh date is dropped.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from app.core.logging import logger

DDG_SEARCH = "https://html.duckduckgo.com/html/?q={query}"
TIMEOUT = httpx.Timeout(30.0, connect=15.0)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}
_DAYS_AGO = re.compile(r"(\d+)\s+day[s]?\s+ago", re.I)
_WEEKS_AGO = re.compile(r"(\d+)\s+week[s]?\s+ago", re.I)
_MONTHS_AGO = re.compile(r"(\d+)\s+month[s]?\s+ago", re.I)
_ISO_ANY = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_MONTH_NAME_FIRST = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
    re.I,
)
_MONTH_NAME_LAST = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*,?\s+(20\d{2})\b",
    re.I,
)
_DATEPOSTED_RE = re.compile(r'"datePosted"\s*:\s*"([^"]+)"')
_HIRING_RE = re.compile(r'"hiringOrganization"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"')

# sites that hide content behind login — deprioritized when picking kept results
_LOGIN_WALLED = ("linkedin", "upwork", "glassdoor", "indeed.com", "ziprecruiter", "monster", "adecco", "remoteok", "weworkremotely", "remotive", "arbeitnow")


def _safe_fromiso(s: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def date_from_text(text: str) -> datetime | None:
    """Parse the first usable date anywhere in free text."""
    for m in _DAYS_AGO.finditer(text):
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    for m in _WEEKS_AGO.finditer(text):
        return datetime.now(timezone.utc) - timedelta(weeks=int(m.group(1)))
    for m in _MONTHS_AGO.finditer(text):
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)) * 30)
    for m in _MONTH_NAME_LAST.finditer(text):
        day, mon_name, year = int(m.group(1)), m.group(2)[:3].lower(), int(m.group(3))
        month = _MONTHS.get(mon_name)
        if month:
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                continue
    for m in _MONTH_NAME_FIRST.finditer(text):
        mon_name, day, year = m.group(1)[:3].lower(), int(m.group(2)), int(m.group(3))
        month = _MONTHS.get(mon_name)
        if month:
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                continue
    for m in _ISO_ANY.finditer(text):
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _iterate_ld(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iterate_ld(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iterate_ld(item)


def extract_details(page_html: str) -> dict:
    """datePosted/hiringOrganization from JobPosting JSON-LD, then broader fallbacks."""
    posted = None
    company = ""

    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in _iterate_ld(data):
            is_job = node.get("@type") == "JobPosting" or (
                isinstance(node.get("@type"), list) and "JobPosting" in node["@type"]
            )
            if is_job:
                posted = posted or _safe_fromiso(node.get("datePosted"))
                org = node.get("hiringOrganization")
                if isinstance(org, dict) and org.get("name"):
                    company = org["name"]
                elif isinstance(org, str):
                    company = org
        if posted or company:
            break

    if not posted:
        m = _DATEPOSTED_RE.search(page_html)
        if m:
            posted = _safe_fromiso(m.group(1))

    if not posted:
        posted = date_from_text(page_html[:300000])

    if not company:
        m = _HIRING_RE.search(page_html)
        if m:
            company = m.group(1)

    return {"posted_at": posted.isoformat() if posted else None, "company": company}


def _parse_ddg_redirect(href: str) -> str:
    parsed = urlparse(href, scheme="https")
    qs = parse_qs(parsed.query)
    if "uddg" in qs:
        return unquote(qs["uddg"][0])
    return href


def parse_serp(html: str) -> list[tuple[str, str, str]]:
    """Extract (title, real_url, snippet) from a DDG HTML result page."""
    results = []
    for m in re.finditer(r'class="result__a"[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href = _parse_ddg_redirect(m.group(1))
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        # snippet lives in the next result__snippet link
        rest = html[m.end():m.end() + 800]
        sm = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', rest, re.S)
        snippet = re.sub(r"<[^>]+>", "", sm.group(1)).strip() if sm else ""
        results.append((title, href, snippet))
    return results


def _domain(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def _domain_score(url: str) -> int:
    """Higher = preferred. Local boards > global jobs pages > login walls."""
    d = _domain(url)
    score = 0
    for hint in ("rw", "rwanda", "kigali", "job", "career"):
        if hint in d:
            score += 2
    if any(w in d for w in _LOGIN_WALLED):
        score -= 3
    if "linkedin" in d:
        score -= 4
    return score


def fetch_page(url: str) -> str:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
        return resp.text if resp.status_code < 400 else ""
    except Exception as exc:
        logger.warning("web_job_page_fetch_failed url=%s err=%s", url, type(exc).__name__)
        return ""


def _search_ddg(query: str) -> str:
    try:
        return httpx.get(DDG_SEARCH.format(query=quote_plus(query)), headers=HEADERS,
                         timeout=TIMEOUT, follow_redirects=True).text
    except Exception as exc:
        logger.warning("web_job_search_failed query=%r error=%s", query, exc)
        return ""


def fetch_web_local(keyword: str, country: str, max_results: int = 6, max_pages: int = 12) -> list[dict]:
    """Three targeted web queries: plain, internship, apprenticeship.

    Each result page is fetched; only listings whose page yields a real
    posting date survive. Returns at most ``max_results`` normalized listings.
    """
    queries = [
        f'"{keyword}" jobs in {country}',
        f'"{keyword}" internship jobs in {country}',
        f'"{keyword}" apprenticeship jobs in {country}',
    ]
    seen_urls: set[str] = set()
    pages_fetched = 0
    out: list[dict] = []

    for query in queries:
        if len(out) >= max_results or pages_fetched >= max_pages:
            break
        html = _search_ddg(query)
        if not html:
            continue

        results = sorted(parse_serp(html), key=lambda r: -_domain_score(r[1]))
        for title, url, snippet in results:
            if len(out) >= max_results or pages_fetched >= max_pages:
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            pages_fetched += 1

            details = extract_details(fetch_page(url))
            posted = _safe_fromiso(details["posted_at"])
            if not posted:
                continue  # cannot prove freshness — skip

            snippet_or_title = f"{title} {snippet}".lower()
            is_remote = bool(re.search(r"\b(remote|anywhere|worldwide|wfh)\b", snippet_or_title))
            company = details["company"] or _domain(url)
            out.append({
                "title": title.strip(),
                "company": company.strip(),
                "location": None if is_remote else country,
                "url": url,
                "source": "web",
                "job_type": None,
                "is_remote": is_remote,
                "posted_at": posted,
            })
        logger.info("web_local_found query=%r kept=%s", query, len(out))

    return out
