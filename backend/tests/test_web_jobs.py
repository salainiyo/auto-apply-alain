from datetime import datetime, timedelta, timezone

import httpx

from app.services import web_jobs

SERP_HTML = """<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.rwandajob.com%2Fjob%2Dvacancies%2Drwa"> PYTHON Developer (M/F) </a>
  <a class="result__snippet" href="#">Senior job: Python Developer at Acme</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fjobsin.rw%2Fpyjobs"> Python jobs in Rwanda </a>
  <a class="result__snippet" href="#">Hired yesterday</a>
</div>
</body></html>"""

JD_HTML = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"Python Dev","datePosted":"2026-10-02","hiringOrganization":{"@type":"Organization","name":"Acme Ltd"},"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressCountry":"Rwanda"}}}
</script></head><body>apply now</body></html>"""


def test_parse_serp():
    rows = web_jobs.parse_serp(SERP_HTML)
    assert len(rows) == 2
    assert rows[0][0].startswith("PYTHON Developer")
    assert rows[0][1] == "https://www.rwandajob.com/job-vacancies-rwa"
    assert rows[1][1] == "https://jobsin.rw/pyjobs"


def test_extract_details_from_jsonld():
    details = web_jobs.extract_details(JD_HTML)
    assert details["posted_at"].startswith("2026-10-02")
    assert details["company"] == "Acme Ltd"


def test_extract_details_days_ago():
    html = "<html><body><p>Posted 7 days ago</p></body></html>"
    details = web_jobs.extract_details(html)
    assert details["posted_at"] is not None


def test_fetch_web_local_workflow(monkeypatch):
    def fake_get(url, **kwargs):
        if "duckduckgo.com/html" in url:
            return httpx.Response(200, text=SERP_HTML, request=httpx.Request("GET", url))
        return httpx.Response(200, text=JD_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    out = web_jobs.fetch_web_local("python", "Rwanda")
    assert out, "expected at least one parsed job listing"
    for job in out:
        assert job["source"] == "web"
        assert job["posted_at"] is not None
        assert job["posted_at"].tzinfo is not None
