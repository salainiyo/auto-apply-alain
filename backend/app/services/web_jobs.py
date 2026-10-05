"""Web job search — finds local jobs by searching the web.

Google blocks scrapers (returns its captcha/consent page), so DuckDuckGo's
HTML endpoint is used instead — it's a plain HTML result page and we filter
and post-process the resulting job-board links ourselves.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from app.core.logging import logger

DDG_SEARCH = "https://html.duckduckgo.com/html/?q={query}"
TIMEOUT = httpx.Timeout(30.0, connect=15.0)
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9"}

_AGO_RE = re.compile(r"(\d+)\s+day[s]?\s+ago|(\d+)\s+month[s]?\s+ago", re.I)
_ANNOUNCED_RE = re.compile(r"(\d+)\s+day[s]?\s+ago", re.I)
_DAYS_AGO_RE = re.compile(r"(\d+)\s+d(ay|ays)?\s+ago", re.I)
_WEEKS_AGO_RE = re.compile(r"(\d+)\s+week[s]?\s+ago", re.I)
_MONTHS_AGO_RE = re.compile(r"(\d+)\s+month[s]?\s+ago", re.I)

JOBLISTING_JSONLD = "JobPosting"


def _parse_ddg_redirect(href: str) -> str:
    href = href.replace("//", "//", 1) if href.startswith("/") else href
    parsed = urlparse(href, scheme="https")
    qs = parse_qs(parsed.query)
    if "uddg" in qs:
        return unquote(qs["uddg"][0])
    return href.lstrip("/")


def parse_serp(html: str) -> list[tuple[str, str, str]]:
    """Extract (title, real_url, snippet) from a DDG HTML result page."""
    results = []
    for block in re.finditer(r'class="result__a"[^>]*?href="([^"]+)"[^>]*>(.*?)</a>\s*.*?class="result__snippet"[^>]*>(.*?)</a>', html, re.S):
        href, raw_title, raw_snippet = block.groups()
        title = re.sub(r"<[^>]+>", "", raw_title)
        snippet = re.sub(r"<[^>]+>", "", raw_snippet)
        results.append((title.strip(), _parse_ddg_redirect(href), snippet.strip()))

    # looser fallback: titles/urls only
    if not results:
        for m in re.finditer(r'class="result__a"[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            results.append((title, _parse_ddg_redirect(m.group(1)), ""))
    return results


def fetch_page(url: str) -> str:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
        if resp.status_code < 400:
            return resp.text
        return ""
    except Exception as exc:
        logger.warning("web_job_page_fetch_failed url=%s err=%s", url, type(exc).__name__)
        return ""


_DATEPOSTED_RE = re.compile(r'"datePosted"\s*:\s*"([^"]+)"')
_HIRING_ORG_RE = re.compile(r'"hiringOrganization"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"')
_DATEPOSTED_PLAIN_RE = re.compile(r'\b(20\d{2}-\d{2}-\d{2})\b')


def extract_details(page_html: str) -> dict:
    """Pull datePosted/hiringOrganization from JobPosting JSON-LD, fallbacks to regex."""
    posted_at = None
    company = ""

    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in _iterate_ld(data):
            if isinstance(node, dict) and (node.get("@type") == "JobPosting" or
                                           (isinstance(node.get("@type"), list) and "JobPosting" in node["@type"])):
                posted_at = _first(node.get("datePosted"), node.get("validThrough") and None) or posted_at
                org = node.get("hiringOrganization")
                if isinstance(org, dict) and org.get("name"):
                    company = org["name"]
                if isinstance(org, str):
                    company = org
        if posted_at or company:
            break

    if not posted_at:
        m = _DATEPOSTED_RE.search(page_html)
        if m:
            posted_at = m.group(1)
        else:
            m = _DATEPOSTED_PLAIN_RE.search(page_html[:200000])
            if m:
                posted_at = m.group(1)

    if not posted_at:
        m = _DAYS_AGO_RE.search(page_html) or _WEEKS_AGO_RE.search(page_html) or _MONTHS_AGO_RE.search(page_html)
        if m:
            n = int(m.group(1))
            now = datetime.now(timezone.utc)
            if _WEEKS_AGO_RE.search(page_html):
                posted_at = (now - timedelta(weeks=n)).strftime("%Y-%m-%d")
            elif _MONTHS_AGO_RE.search(page_html):
                posted_at = (now - timedelta(days=n * 30)).strftime("%Y-%m-%d")
            else:
                posted_at = (now - timedelta(days=n)).strftime("%Y-%m-%d")

    if not company:
        m = _HIRING_ORG_RE.search(page_html)
        if m:
            company = m.group(1)

    return {"posted_at": posted_at, "company": company}


def _iterate_ld(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iterate_ld(v)
    elif isinstance(node, list):
        for i in node:
            yield from _iterate_ld(i)


def _first(*values):
    return next((v for v in values if v), None)


def _domain(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def fetch_web_local(keyword: str, country: str, max_results: int = 6) -> list[dict]:
    """Web results for "<keyword> jobs in <country>" — each link briefly scraped
    for its real posting date; entries with no date are dropped by the caller's
    expiry filter."""
    query = f"{keyword} jobs in {country}"
    try:
        html = httpx.get(DDG_SEARCH.format(query=quote_plus(query)), headers=HEADERS, timeout=TIMEOUT, follow_redirects=True).text
    except Exception as exc:
        logger.warning("web_job_search_failed query=%r error=%s", query, exc)
        return []

    results = parse_serp(html)
    listings = []
    for title, url, snippet in results:
        if len(listings) >= max_results:
            break
        snippet_or_title = f"{title} {snippet}".lower()
        is_remote = bool(re.search(r"\b(remote|anywhere|worldwide|wfh)\b", snippet_or_title))

        details = {"posted_at": None, "company": ""}
        if url:
            details = extract_details(fetch_page(url)) if len(listings) < max_results * 2 else details

        if details.get("posted_at"):
            try:
                posted = datetime.fromisoformat(str(details["posted_at"]).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                try:
                    posted = parsedate_to_datetime(str(details["posted_at"]))
                except (ValueError, TypeError):
                    continue
        else:
            # no usable date on the page — we cannot prove it is still open
            continue

        company = details.get("company") or _domain(url)
        listings.append(_listing(title=title, company=company, url=url, note=snippet,
                                 country=country, is_remote=is_remote, posted=posted))
    logger.info("web_local_found query=%r kept=%s of %s", query, len(listings), len(results))
    return listings


def _listing(*, title, company, url, note, country, is_remote, posted):
    return {
        "title": title.strip(),
        "company": (company or "").strip(),
        "location": None if is_remote else country,
        "url": url,
        "source": "web",
        "job_type": None,
        "is_remote": is_remote,
        "posted_at": posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc),
        "note": note,
    }
