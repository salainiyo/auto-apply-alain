from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from app.core.config import settings
from app.core.security import create_access_token
from tests.conftest import (
    DEFAULT_EMAIL,
    DEFAULT_PASSWORD,
    auth_headers,
    extract_token,
    get_user_id,
    login,
    register_and_verify,
)


async def test_forgot_password_sends_email(ctx):
    await register_and_verify(ctx)

    resp = await ctx.client.post("/auth/forgot-password", json={"email": DEFAULT_EMAIL})
    assert resp.status_code == 200, resp.text

    assert len(ctx.sent_emails) == 2
    assert "reset" in ctx.sent_emails[-1]["subject"].lower()
    assert ctx.sent_emails[-1]["to"] == DEFAULT_EMAIL


async def test_forgot_password_unknown_email_no_enumeration(ctx):
    resp = await ctx.client.post("/auth/forgot-password", json={"email": "ghost@test.com"})
    assert resp.status_code == 200
    assert "if that email exists" in resp.json()["message"].lower()
    assert len(ctx.sent_emails) == 0


async def test_reset_password_full_flow(ctx):
    await register_and_verify(ctx)
    await ctx.client.post("/auth/forgot-password", json={"email": DEFAULT_EMAIL})

    token = extract_token(ctx.sent_emails[-1]["html"])
    resp = await ctx.client.post(
        "/auth/reset-password", json={"token": token, "new_password": "NewPassword1"}
    )
    assert resp.status_code == 200, resp.text

    old_login = await login(ctx, password=DEFAULT_PASSWORD)
    assert old_login.status_code == 401

    new_login = await login(ctx, password="NewPassword1")
    assert new_login.status_code == 200


async def test_reset_password_invalid_token(ctx):
    resp = await ctx.client.post(
        "/auth/reset-password", json={"token": "garbage", "new_password": "NewPassword1"}
    )
    assert resp.status_code == 400


async def test_reset_password_expired_token(ctx):
    await register_and_verify(ctx)
    user_id = await get_user_id(ctx)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "password_reset",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
        "jti": "expired-reset",
    }
    expired = pyjwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)

    resp = await ctx.client.post(
        "/auth/reset-password", json={"token": expired, "new_password": "NewPassword1"}
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


async def test_reset_password_rejects_wrong_token_type(ctx):
    await register_and_verify(ctx)
    user_id = await get_user_id(ctx)
    access = create_access_token(str(user_id))

    resp = await ctx.client.post(
        "/auth/reset-password", json={"token": access, "new_password": "NewPassword1"}
    )
    assert resp.status_code == 400


async def test_change_password_success(ctx):
    headers = await auth_headers(ctx)

    resp = await ctx.client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": DEFAULT_PASSWORD, "new_password": "NewPassword1"},
    )
    assert resp.status_code == 200, resp.text

    old_login = await login(ctx, password=DEFAULT_PASSWORD)
    assert old_login.status_code == 401

    new_login = await login(ctx, password="NewPassword1")
    assert new_login.status_code == 200


async def test_change_password_wrong_current(ctx):
    headers = await auth_headers(ctx)

    resp = await ctx.client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": "WrongPassword1", "new_password": "NewPassword1"},
    )
    assert resp.status_code == 400
    assert "incorrect" in resp.json()["detail"].lower()


async def test_change_password_requires_auth(ctx):
    resp = await ctx.client.post(
        "/auth/change-password",
        json={"current_password": "Whatever1", "new_password": "NewPassword1"},
    )
    assert resp.status_code == 401
