import json

import redis

from app.core.config import settings
from app.core.logging import logger

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def publish_progress(user_id: str, job: str, status: str, detail: str = "") -> None:
    """Publish a pipeline progress event on the user's Redis channel.

    The WebSocket endpoint (/ws/progress) streams these to the browser.
    Best-effort: never crashes the caller.
    """
    try:
        _get_client().publish(
            f"progress:{user_id}",
            json.dumps({"job": job, "status": status, "detail": detail}),
        )
    except Exception as exc:
        logger.warning("progress_publish_failed user_id=%s error=%s", user_id, exc)
