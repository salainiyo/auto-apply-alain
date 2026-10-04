import re
from types import SimpleNamespace

import pytest_asyncio
from fakeredis import aioredis as fakeredis_aioredis
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import create_email_verify_token
from app.db.database import Base, get_db
from app.db.models import User
from app.main import app
from app.middleware.redis_client import get_redis
from app.services import email_service

CONTAINER_DB_URL = "postgresql+asyncpg://alain:changepassword@localhost:5433"
TEST_DB_NAME = "auto_apply_test"
TEST_DB_URL = f"{CONTAINER_DB_URL}/{TEST_DB_NAME}"

DEFAULT_EMAIL = "user@test.com"
DEFAULT_PASSWORD = "SuperSecret1"
DEFAULT_COUNTRY = "Germany"


def extract_token(html: str) -> str:
    match = re.search(r"token=([A-Za-z0-9._\-]+)", html)
    assert match, f"No token found in email html: {html!r}"
    return match.group(1)


@pytest_asyncio.fixture
async def ctx(monkeypatch):
    admin_engine = create_async_engine(
        CONTAINER_DB_URL + "/postgres", isolation_level="AUTOCOMMIT"
    )
    async with admin_engine.connect() as conn:
        try:
            await conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
        except Exception:
            pass
    await admin_engine.dispose()

    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    fake_redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
    sent_emails: list[dict] = []

    async def fake_send(to: str, subject: str, html: str) -> None:
        sent_emails.append({"to": to, "subject": subject, "html": html})

    monkeypatch.setattr(email_service, "send_email", fake_send)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = lambda: fake_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            sent_emails=sent_emails,
            session_factory=session_factory,
        )

    app.dependency_overrides.clear()
    await engine.dispose()


async def get_user_id(ctx, email: str = DEFAULT_EMAIL):
    from sqlalchemy import select

    async with ctx.session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one().id


async def register_user(
    ctx,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    country: str = DEFAULT_COUNTRY,
):
    return await ctx.client.post(
        "/auth/register",
        json={"email": email, "password": password, "country": country},
    )


async def verify_user(ctx, email: str = DEFAULT_EMAIL):
    token = extract_token(ctx.sent_emails[-1]["html"])
    return await ctx.client.post("/auth/verify-email", json={"token": token})


async def register_and_verify(
    ctx,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
    country: str = DEFAULT_COUNTRY,
):
    resp = await register_user(ctx, email=email, password=password, country=country)
    assert resp.status_code == 201, resp.text
    vresp = await verify_user(ctx, email=email)
    assert vresp.status_code == 200, vresp.text


async def login(ctx, email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD):
    return await ctx.client.post(
        "/auth/login", json={"email": email, "password": password}
    )


async def auth_headers(
    ctx,
    email: str = DEFAULT_EMAIL,
    password: str = DEFAULT_PASSWORD,
) -> dict:
    await register_and_verify(ctx, email=email, password=password)
    resp = await login(ctx, email=email, password=password)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
