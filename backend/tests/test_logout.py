from sqlalchemy import select

from app.db.models import RevokedToken
from tests.conftest import login, register_and_verify


async def test_logout_saves_token_in_db(ctx):
    await register_and_verify(ctx)
    login_resp = await login(ctx)
    access = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    resp = await ctx.client.post("/auth/logout", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "logged out" in resp.json()["message"].lower()

    async with ctx.session_factory() as session:
        rows = (await session.execute(select(RevokedToken))).scalars().all()
        assert len(rows) == 1


async def test_token_unusable_after_logout(ctx):
    await register_and_verify(ctx)
    login_resp = await login(ctx)
    access = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    await ctx.client.post("/auth/logout", headers=headers)

    me = await ctx.client.get("/users/me", headers=headers)
    assert me.status_code == 401
    assert "revoked" in me.json()["detail"].lower()


async def test_logout_requires_auth(ctx):
    resp = await ctx.client.post("/auth/logout")
    assert resp.status_code == 401


async def test_logout_with_invalid_token(ctx):
    resp = await ctx.client.post(
        "/auth/logout", headers={"Authorization": "Bearer garbage"}
    )
    assert resp.status_code == 401
