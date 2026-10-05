import httpx

from app.services import ai_service

GEMINI_MODELS_PAYLOAD = {
    "models": [
        {
            "name": "models/gemini-2.5-pro",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-2.5-flash",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/gemini-3-pro-preview",
            "supportedGenerationMethods": ["generateContent"],
        },
        {
            "name": "models/veo-3.1",
            "supportedGenerationMethods": ["predictLongRunning"],
        },
    ]
}

SUCCESS_PAYLOAD = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}


def _resp(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status, json=payload, request=httpx.Request("POST", "https://example")
    )


def test_call_gemini_uses_configured_model_when_available(monkeypatch):
    ai_service._model_cache.clear()
    posted_urls = []

    monkeypatch.setattr(
        ai_service,
        "_http_post",
        lambda url, body, params=None: posted_urls.append(url) or _resp(200, SUCCESS_PAYLOAD),
    )
    monkeypatch.setattr(
        ai_service, "_http_get", lambda url, params=None: _resp(200, GEMINI_MODELS_PAYLOAD)
    )

    assert ai_service.call_gemini("hello") == "{}"
    assert "gemini-2.5-flash" in posted_urls[0]


def test_call_gemini_skips_missing_model_when_list_available(monkeypatch):
    """Configured model absent from the list -> fallback is used from the start."""
    ai_service._model_cache.clear()
    posted_urls = []

    monkeypatch.setattr(
        ai_service,
        "_http_post",
        lambda url, body, params=None: posted_urls.append(url) or _resp(200, SUCCESS_PAYLOAD),
    )
    monkeypatch.setattr(
        ai_service, "_http_get", lambda url, params=None: _resp(200, GEMINI_MODELS_PAYLOAD)
    )
    monkeypatch.setattr(ai_service.settings, "gemini_model", "gemini-old-model")

    assert ai_service.call_gemini("hello") == "{}"
    assert "gemini-2.5-flash" in posted_urls[0]  # never posts with the dead model


def test_call_gemini_retries_with_fallback_on_404(monkeypatch):
    """Configured model in the list but 404s (removed) -> retry with fallback."""
    ai_service._model_cache.clear()
    posted_urls = []

    def fake_post(url, body, params=None):
        posted_urls.append(url)
        if len(posted_urls) == 1:
            return _resp(404, {"error": "model not found"})
        return _resp(200, SUCCESS_PAYLOAD)

    monkeypatch.setattr(ai_service, "_http_post", fake_post)
    monkeypatch.setattr(
        ai_service, "_http_get", lambda url, params=None: _resp(200, GEMINI_MODELS_PAYLOAD)
    )
    monkeypatch.setattr(ai_service.settings, "gemini_model", "gemini-2.5-pro")

    assert ai_service.call_gemini("hello") == "{}"
    assert "gemini-2.5-pro" in posted_urls[0]
    assert "gemini-2.5-flash" in posted_urls[1]


def test_model_choice_is_cached(monkeypatch):
    ai_service._model_cache.clear()
    get_calls = []

    monkeypatch.setattr(ai_service, "_http_post", lambda *a, **k: _resp(200, SUCCESS_PAYLOAD))
    monkeypatch.setattr(
        ai_service,
        "_http_get",
        lambda url, params=None: get_calls.append(url) or _resp(200, GEMINI_MODELS_PAYLOAD),
    )

    ai_service.call_gemini("a")
    ai_service.call_gemini("b")
    assert len(get_calls) == 1  # only fetched the model list once


def test_pick_model_prefers_non_preview_flash(monkeypatch):
    ai_service._model_cache.clear()
    monkeypatch.setattr(
        ai_service, "_http_get", lambda url, params=None: _resp(200, GEMINI_MODELS_PAYLOAD)
    )

    assert ai_service._pick_model("gemini-nonexistent") == "gemini-2.5-flash"


def test_pick_model_lists_fallback_when_list_unavailable(monkeypatch):
    ai_service._model_cache.clear()
    monkeypatch.setattr(ai_service, "_http_get", lambda url, params=None: (_ for _ in ()).throw(RuntimeError("no network")))

    # cannot list models -> keep configured model
    assert ai_service._pick_model("gemini-2.5-flash") == "gemini-2.5-flash"
