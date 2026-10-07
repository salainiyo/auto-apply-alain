
import re
import json

import httpx

from app.core.config import settings
from app.core.logging import logger

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

EXTRACTION_PROMPT = """You are an expert career advisor.
Given the resume text below and the candidate's residence country, extract the concrete job roles this candidate can realistically apply to.

Rules:
- Return between 3 and 8 roles.
- Include internships and apprenticeships where appropriate for the candidate's experience level.
- Each role must have a "title" (job title) and "keywords" (3-6 search keywords to find this job online, localized to the residence country).
- Return ONLY valid JSON in this exact shape:
{{"roles": [{{"title": "...", "keywords": ["...", "..."]}}]}}

Resume:
{resume_text}

Residence country: {country}
"""

_model_cache: dict = {}


def _http_get(url: str, params: dict | None = None) -> httpx.Response:
    with httpx.Client(timeout=30) as client:
        return client.get(url, params=params, headers={"User-Agent": "auto-apply-alain/0.1"})


def _http_post(url: str, body: dict, params: dict | None = None) -> httpx.Response:
    with httpx.Client(timeout=60) as client:
        return client.post(url, json=body, params=params)


def _fetch_model_names() -> list[str]:
    """Gemini model names supporting generateContent, without the 'models/' prefix."""
    try:
        resp = _http_get(f"{GEMINI_BASE_URL}/models", params={"pageSize": 100, "key": settings.gemini_api_key})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("gemini_model_list_failed error=%s", exc)
        return []

    names = []
    for model in data.get("models", []) or []:
        name = (model.get("name") or "").removeprefix("models/")
        if "gemini" in name and "generateContent" in (model.get("supportedGenerationMethods") or []):
            names.append(name)
    return names


def _score_model(name: str) -> int:
    """Higher is better: stable over preview, flash over pro over lite."""
    score = 0
    if "preview" not in name and "exp" not in name:
        score += 100
    if "flash" in name:
        score += 10
    elif "pro" in name:
        score += 5
    if "lite" in name:
        score -= 1
    return score


def _pick_model(preferred: str, exclude: set[str] | None = None) -> str:
    exclude = exclude or set()
    all_names = _fetch_model_names()
    names = [n for n in all_names if n not in exclude]
    if not names:
        return preferred  # nothing known -> try the configured one anyway
    if preferred in names:
        return preferred
    best = max(names, key=_score_model)
    logger.info("gemini_model_fallback configured=%s fallback=%s", preferred, best)
    return best


def get_model(exclude: set[str] | None = None) -> str:
    if exclude:
        return _pick_model(settings.gemini_model, exclude=exclude)
    cached = _model_cache.get("model")
    if cached:
        return cached
    model = _pick_model(settings.gemini_model)
    _model_cache["model"] = model
    return model


def invalidate_model_cache() -> None:
    _model_cache.pop("model", None)


def call_gemini(prompt: str) -> str:
    """Call the Gemini API and return the raw text response.

    Falls back to any available model when the configured one is not
    available (403/404), then caches the working choice.
    """
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    }
    last_error: Exception | None = None
    exclude: set[str] = set()
    for attempt in range(2):
        model = get_model(exclude=exclude or None)
        try:
            resp = _http_post(
                f"{GEMINI_BASE_URL}/models/{model}:generateContent",
                body,
                params={"key": settings.gemini_api_key},
            )
            if resp.status_code in (403, 404) and attempt == 0:
                logger.warning("gemini_model_unavailable model=%s status=%s", model, resp.status_code)
                exclude.add(model)
                invalidate_model_cache()
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            break
    assert last_error is not None
    raise last_error


COVER_LETTER_PROMPT = """You are a professional career coach.
Based on the candidate's resume and this job listing, write a concise, tailored cover letter of about 170-200 words.
- Professional, warm, direct tone
- Name 2-3 skills/requirements from the listing that match the resume
- Reference the candidate's country only where relevant
- Sign off with a polite close and the candidate's email
Return ONLY the letter text. No subject line, no JSON, no headers.

Candidate resume:
{resume_text}

Job title: {job_title}
Candidate country: {candidate_country}
Job info:
{job_text}
"""


def call_gemini_text(prompt: str) -> str:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4},
    }
    last_error: Exception | None = None
    exclude: set[str] = set()
    for attempt in range(2):
        model = get_model(exclude=exclude or None)
        try:
            resp = _http_post(
                f"{GEMINI_BASE_URL}/models/{model}:generateContent",
                body,
                params={"key": settings.gemini_api_key},
            )
            if resp.status_code in (403, 404) and attempt == 0:
                exclude.add(model)
                invalidate_model_cache()
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            break
    assert last_error is not None
    raise last_error


def build_cover_letter(resume_text: str, job_title: str, job_text: str, candidate_country: str) -> str:
    prompt = COVER_LETTER_PROMPT.format(
        resume_text=resume_text[:12000],
        job_title=job_title[:120],
        job_text=re.sub(r"<[^>]+>", " ", job_text)[:4000],
        candidate_country=candidate_country,
    )
    return call_gemini_text(prompt).strip().strip('"')


def parse_roles(raw: str) -> list[dict]:
    data = json.loads(raw)
    roles: list[dict] = []
    for item in data.get("roles", []):
        title = (item.get("title") or "").strip()
        keywords = [k.strip() for k in item.get("keywords", []) if isinstance(k, str) and k.strip()]
        if title:
            roles.append({"title": title, "keywords": keywords})
    return roles


def extract_roles(resume_text: str, country: str) -> list[dict]:
    """Send the resume to Gemini and parse the suggested roles."""
    prompt = EXTRACTION_PROMPT.format(resume_text=resume_text[:15000], country=country)
    raw = call_gemini(prompt)
    roles = parse_roles(raw)
    logger.info("gemini_roles_extracted count=%s", len(roles))
    return roles
