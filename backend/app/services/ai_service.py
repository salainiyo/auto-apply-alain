import json

import httpx

from app.core.config import settings
from app.core.logging import logger

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

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


def call_gemini(prompt: str) -> str:
    """Call the Gemini API and return the raw text response."""
    url = GEMINI_API_URL.format(model=settings.gemini_model)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    }
    with httpx.Client(timeout=60) as client:
        resp = client.post(url, json=body, params={"key": settings.gemini_api_key})
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


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
