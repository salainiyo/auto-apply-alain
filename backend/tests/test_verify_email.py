from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.db.models import User
from tests.conftest import (
    DEFAULT_EMAIL,
    DEFAULT_PASSWORD,
    extract_token,
    get_user_id,
    register_and_verify,
    register_user,
)


async def test_verify_email_success(ctx):
    await register_user(ctx)
    token = extract_token(ctx.sent_emails[-1]["html"])

    resp = await ctx.client.post("/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text

    async with ctx.session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == DEFAULT_EMAIL))
        ).scalar_one()
        assert user.is_verified is True

    login_resp = await ctx.client.post(
        "/auth/login", json={"email": DEFAULT_EMAIL, "password": DEFAULT_PASSWORD}
    )
    assert login_resp.status_code == 200


async def test_verify_email_invalid_token(ctx):
    resp = await ctx.client.post("/auth/verify-email", json={"token": "garbage-token"})
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"].lower()


async def test_verify_email_expired_token(ctx):
    await register_user(ctx)
    user_id = await get_user_id(ctx)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "email_verify",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
        "jti": "expired-jti",
    }
    expired = pyjwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

    resp = await ctx.client.post("/auth/verify-email", json={"token": expired})
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


async def test_verify_email_rejects_wrong_token_type(ctx):
    await register_user(ctx)
    user_id = await get_user_id(ctx)
    access = create_access_token(str(user_id))

    resp = await ctx.client.post("/auth/verify-email", json={"token": access})
    assert resp.status_code == 400


async def test_verify_email_unknown_user(ctx):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "00000000-0000-0000-0000-000000000000",
        "type": "email_verify",
        "iat": now,
        "exp": now + timedelta(hours=1),
        "jti": "unknown-user-jti",
    }
    token = pyjwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

    resp = await ctx.client.post("/auth/verify-email", json={"token": token})
    assert resp.status_code == 400


async def test_verify_email_already_verified(ctx):
    await register_and_verify(ctx)
    token = extract_token(ctx.sent_emails[-1]["html"])

    resp = await ctx.client.post("/auth/verify-email", json={"token": token})
    assert resp.status_code == 200
    assert "already" in resp.json()["message"].lower()
