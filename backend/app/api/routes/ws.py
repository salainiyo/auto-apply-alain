import asyncio
import json

import jwt as pyjwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis

from app.core.config import settings
from app.core.logging import logger
from app.core.security import ACCESS_TOKEN_TYPE, decode_token

router = APIRouter(tags=["ws"])


@router.websocket("/ws/progress")
async def ws_progress(websocket: WebSocket):
    token = websocket.query_params.get("token")

    payload = None
    if token:
        try:
            payload = decode_token(token)
        except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
            payload = None

    if not payload or payload.get("type") != ACCESS_TOKEN_TYPE:
        await websocket.close(code=4401)
        return

    user_id = payload.get("sub")
    await websocket.accept()

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(f"progress:{user_id}")
        await websocket.send_json({"type": "connected"})

        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                data = message.get("data")
                try:
                    await websocket.send_json(json.loads(data) if isinstance(data, str) else data)
                except Exception:
                    break
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("ws_progress_error error=%s", exc)
    finally:
        try:
            await pubsub.unsubscribe(f"progress:{user_id}")
        except Exception:
            pass
        try:
            close = getattr(r, "aclose", None) or getattr(r, "close", None)
            if close:
                await close()
        except Exception:
            pass
