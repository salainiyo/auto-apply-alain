from sqlalchemy import select

from app.db.models import User
from tests.conftest import DEFAULT_COUNTRY, DEFAULT_EMAIL, DEFAULT_PASSWORD, register_user


async def test_register_success(ctx):
    resp = await register_user(ctx)
    assert resp.status_code == 201, resp.text
    assert "verify" in resp.json()["message"].lower()

    assert len(ctx.sent_emails) == 1
    assert ctx.sent_emails[0]["to"] == DEFAULT_EMAIL

    async with ctx.session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == DEFAULT_EMAIL))
        ).scalar_one()
        assert user.is_verified is False
        assert user.country == DEFAULT_COUNTRY
        assert user.hashed_password != DEFAULT_PASSWORD
        assert user.hashed_password.startswith("$argon2")


async def test_register_duplicate_email(ctx):
    await register_user(ctx)
    resp = await register_user(ctx)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Email already registered"
    assert len(ctx.sent_emails) == 1


async def test_register_invalid_email(ctx):
    resp = await ctx.client.post(
        "/auth/register",
        json={"email": "not-an-email", "password": DEFAULT_PASSWORD, "country": "Germany"},
    )
    assert resp.status_code == 422


async def test_register_weak_password(ctx):
    resp = await ctx.client.post(
        "/auth/register",
        json={"email": "new@test.com", "password": "short", "country": "Germany"},
    )
    assert resp.status_code == 422


async def test_register_missing_country(ctx):
    resp = await ctx.client.post(
        "/auth/register",
        json={"email": "new@test.com", "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 422
