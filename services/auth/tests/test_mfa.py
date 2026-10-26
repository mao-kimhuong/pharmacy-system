import pyotp

from .conftest import PREFIX, audit_actions, login, make_user, totp, verify


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_owner_without_2fa_gets_a_setup_only_token(client) -> None:
    await make_user(role="owner")
    data = (await login(client)).json()
    assert data["mfa_setup_required"] is True
    token = data["access_token"]
    blocked = await verify(client, token, "/api/sales/v1/whoami")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "MFA_SETUP_REQUIRED"
    for path in (
        "/api/auth/v1/2fa/setup",
        "/api/auth/v1/2fa/enable",
        "/api/auth/v1/me",
        "/api/auth/v1/logout",
    ):
        assert (await verify(client, token, path)).status_code == 200, path


async def test_manager_must_also_use_2fa(client) -> None:
    await make_user(role="branch_manager")
    assert (await login(client)).json()["mfa_setup_required"] is True


async def test_cashier_does_not_need_2fa(client) -> None:
    await make_user(role="cashier")
    data = (await login(client)).json()
    assert "mfa_setup_required" not in data or data["mfa_setup_required"] is False
    assert (await verify(client, data["access_token"])).status_code == 200


async def test_full_setup_then_login_with_code(client) -> None:
    await make_user(role="owner")
    setup_token = (await login(client)).json()["access_token"]

    setup = await client.post(f"{PREFIX}/2fa/setup", headers=bearer(setup_token))
    assert setup.status_code == 200
    body = setup.json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["qr_svg"].startswith("data:image/svg+xml;base64,")
    secret = body["secret"]

    wrong = await client.post(f"{PREFIX}/2fa/enable", json={"code": "000000"}, headers=bearer(setup_token))
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "INVALID_MFA_CODE"

    enabled = await client.post(
        f"{PREFIX}/2fa/enable", json={"code": totp(secret)}, headers=bearer(setup_token)
    )
    assert enabled.status_code == 200
    new_token = enabled.json()["access_token"]
    assert (await verify(client, new_token)).status_code == 200
    assert (await verify(client, setup_token, "/api/auth/v1/me")).status_code == 401  # set-up token ended
    assert "user.2fa_enabled" in await audit_actions()

    # next login asks for the code
    step1 = (await login(client, ip="10.0.0.2")).json()
    assert step1["mfa_required"] is True
    assert "access_token" not in step1
    step2 = await client.post(
        f"{PREFIX}/login/2fa", json={"mfa_token": step1["mfa_token"], "code": totp(secret, steps_ahead=1)}
    )
    assert step2.status_code == 200
    assert (await verify(client, step2.json()["access_token"])).status_code == 200


async def test_a_code_works_only_once(client) -> None:
    secret = pyotp.random_base32()
    await make_user(role="owner", totp_secret=secret)
    code = totp(secret)
    first = (await login(client, ip="10.0.0.1")).json()["mfa_token"]
    assert (
        await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": first, "code": code})
    ).status_code == 200
    second = (await login(client, ip="10.0.0.2")).json()["mfa_token"]
    r = await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": second, "code": code})
    assert r.status_code == 401
    assert r.json()["code"] == "INVALID_MFA_CODE"


async def test_mfa_token_works_only_once(client) -> None:
    secret = pyotp.random_base32()
    await make_user(role="owner", totp_secret=secret)
    mfa = (await login(client)).json()["mfa_token"]
    assert (
        await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": mfa, "code": totp(secret)})
    ).status_code == 200
    again = await client.post(
        f"{PREFIX}/login/2fa", json={"mfa_token": mfa, "code": totp(secret, steps_ahead=1)}
    )
    assert again.status_code == 401


async def test_wrong_codes_count_towards_lockout(client) -> None:
    secret = pyotp.random_base32()
    await make_user(role="owner", totp_secret=secret)
    statuses = []
    for i in range(10):
        mfa = (await login(client, ip=f"10.5.0.{i}")).json()["mfa_token"]
        r = await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": mfa, "code": "000000"})
        statuses.append(r.status_code)
    assert statuses[:9] == [401] * 9
    assert statuses[9] == 423


async def test_forged_mfa_token_is_refused(client) -> None:
    r = await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": "not-a-token", "code": "123456"})
    assert r.status_code == 401


async def test_secret_is_stored_encrypted(client) -> None:
    from sqlalchemy import text

    from auth_service.db import db

    await make_user(role="owner")
    token = (await login(client)).json()["access_token"]
    secret = (await client.post(f"{PREFIX}/2fa/setup", headers=bearer(token))).json()["secret"]
    async with db.engine.connect() as conn:
        stored = (await conn.execute(text("SELECT totp_secret_enc FROM users"))).scalar_one()
    assert secret not in stored


async def test_cannot_set_up_twice(client) -> None:
    secret = pyotp.random_base32()
    await make_user(role="cashier", totp_secret=secret)
    mfa = (await login(client)).json()["mfa_token"]  # cashier who turned 2FA on must use it too
    token = (await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": mfa, "code": totp(secret)})).json()[
        "access_token"
    ]
    assert (await client.post(f"{PREFIX}/2fa/setup", headers=bearer(token))).status_code == 409
