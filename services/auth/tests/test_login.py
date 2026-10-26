from uuid import UUID

from .conftest import PASSWORD, PREFIX, login, make_user, outbox_types

BRANCH = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


async def test_login_returns_tokens_and_user(client) -> None:
    await make_user(branches=(BRANCH,), is_pharmacist=True)
    r = await login(client)
    assert r.status_code == 200
    data = r.json()
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 15 * 60
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["phone"] == "012345678"
    assert data["user"]["role"] == "cashier"
    assert data["user"]["is_pharmacist"] is True
    assert data["user"]["branch_ids"] == [str(BRANCH)]
    assert "password_hash" not in data["user"]
    assert await outbox_types() == ["user.logged_in"]


async def test_wrong_password_and_unknown_phone_give_the_same_answer(client) -> None:
    await make_user()
    wrong_password = await login(client, password="nope-nope")
    unknown_phone = await login(client, phone="099999999")
    assert wrong_password.status_code == unknown_phone.status_code == 401
    assert wrong_password.json() == unknown_phone.json()
    assert wrong_password.json()["code"] == "INVALID_CREDENTIALS"


async def test_invalid_phone_format_is_invalid_credentials(client) -> None:
    r = await login(client, phone="hello")
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_CREDENTIALS"


async def test_inactive_user_cannot_log_in(client) -> None:
    await make_user(is_active=False)
    r = await login(client)
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_CREDENTIALS"


async def test_phone_is_normalized(client) -> None:
    await make_user(phone="012345678")
    assert (await login(client, phone="+855 12 345 678")).status_code == 200
    assert (await login(client, phone="012-345-678", ip="10.0.0.2")).status_code == 200


async def test_successful_login_resets_failed_attempts(client) -> None:
    await make_user()
    for _ in range(3):
        await login(client, password="wrong-pass", ip="10.0.1.1")
    assert (await login(client, ip="10.0.1.2")).status_code == 200
    # 9 more failures must not lock: the counter started again from 0
    for i in range(9):
        r = await login(client, password="wrong-pass", ip=f"10.0.2.{i}")
        assert r.status_code == 401


async def test_validation_errors_never_echo_the_password(client) -> None:
    r = await client.post(
        f"{PREFIX}/login", json={"phone": "012345678", "password": PASSWORD, "role": "owner"}
    )
    assert r.status_code == 422
    assert PASSWORD not in r.text
    assert r.json()["code"] == "VALIDATION_ERROR"


async def test_login_rate_limit_per_ip_and_phone(client) -> None:
    await make_user()
    for _ in range(5):
        await login(client, password="wrong-pass", ip="10.9.9.9")
    r = await login(client, ip="10.9.9.9")
    assert r.status_code == 429
    assert r.json()["code"] == "RATE_LIMITED"
    assert "retry-after" in r.headers
    # another IP is not blocked
    assert (await login(client, ip="10.9.9.10")).status_code == 200
