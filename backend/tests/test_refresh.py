from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from sqlalchemy import select

from app.core.config import settings
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.models import User
from tests.conftest import DEFAULT_EMAIL, login, register_and_verify


async def _login_tokens(ctx) -> dict:
    resp = await login(ctx)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_refresh_success(ctx):
    await register_and_verify(ctx)
    tokens = await _login_tokens(ctx)

    resp = await ctx.client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text

    payload = decode_token(resp.json()["access_token"])
    assert payload["type"] == ACCESS_TOKEN_TYPE
    assert payload["sub"]


async def test_refresh_rejects_access_token(ctx):
    await register_and_verify(ctx)
    tokens = await _login_tokens(ctx)

    resp = await ctx.client.post(
        "/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert resp.status_code == 401
    assert "token type" in resp.json()["detail"].lower()


async def test_refresh_invalid_token(ctx):
    resp = await ctx.client.post("/auth/refresh", json={"refresh_token": "garbage"})
    assert resp.status_code == 401


async def test_refresh_expired_token(ctx):
    await register_and_verify(ctx)
    await _login_tokens(ctx)

    async with ctx.session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == DEFAULT_EMAIL))
        ).scalar_one()

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "type": "refresh",
        "iat": now - timedelta(days=2),
        "exp": now - timedelta(days=1),
        "jti": "expired-refresh",
    }
    expired = pyjwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

    resp = await ctx.client.post("/auth/refresh", json={"refresh_token": expired})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()
