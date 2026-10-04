from tests.conftest import DEFAULT_COUNTRY, DEFAULT_EMAIL, auth_headers


async def test_me_authenticated(ctx):
    headers = await auth_headers(ctx)

    resp = await ctx.client.get("/users/me", headers=headers)
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert data["email"] == DEFAULT_EMAIL
    assert data["country"] == DEFAULT_COUNTRY
    assert data["is_verified"] is True
    assert data["id"]
    assert data["created_at"]


async def test_me_unauthorized(ctx):
    resp = await ctx.client.get("/users/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


async def test_me_with_garbage_token(ctx):
    resp = await ctx.client.get("/users/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


async def test_health(ctx):
    resp = await ctx.client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
