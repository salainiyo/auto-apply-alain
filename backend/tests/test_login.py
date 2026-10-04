from tests.conftest import (
    DEFAULT_EMAIL,
    DEFAULT_PASSWORD,
    login,
    register_and_verify,
    register_user,
)


async def test_login_success(ctx):
    await register_and_verify(ctx)
    resp = await login(ctx)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(ctx):
    await register_and_verify(ctx)
    resp = await login(ctx, password="WrongPassword1")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_login_unknown_email(ctx):
    resp = await login(ctx, email="ghost@test.com")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_login_unverified_account(ctx):
    await register_user(ctx)
    resp = await login(ctx)
    assert resp.status_code == 403
    assert "not verified" in resp.json()["detail"].lower()


async def test_login_rate_limited_after_five_attempts(ctx):
    await register_and_verify(ctx)

    statuses = []
    for _ in range(6):
        r = await login(ctx, password="WrongPassword1")
        statuses.append(r.status_code)

    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
