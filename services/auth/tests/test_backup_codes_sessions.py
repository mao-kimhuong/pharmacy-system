"""2FA backup codes (shown once, used once, wrong ones count as failed attempts,
regenerated with the password) and your sessions (listed, current marked, revoked
at once)."""

from uuid import UUID

from auth_service.db import db
from auth_service.services import backup_codes

from .conftest import PASSWORD, PREFIX, audit_actions, login, make_user, totp, verify


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def owner_with_2fa(client) -> tuple[str, list[str], str]:  # noqa: ANN001
    user = await make_user(role="owner")
    setup_token = (await login(client)).json()["access_token"]
    secret = (await client.post(f"{PREFIX}/2fa/setup", headers=bearer(setup_token))).json()["secret"]
    enabled = (await client.post(f"{PREFIX}/2fa/enable", json={"code": totp(secret)}, headers=bearer(setup_token))).json()
    return enabled["access_token"], enabled["backup_codes"], str(user.id)


STEP = iter(range(10, 250))


async def second_step(client, body: dict):  # noqa: ANN001, ANN201
    r = await login(client, ip=f"10.0.1.{next(STEP)}")  # the login rate limit counts per IP and phone
    assert "mfa_token" in r.json(), r.text
    mfa = r.json()["mfa_token"]
    return await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": mfa, **body})


async def test_backup_codes_shown_once_used_once_and_regenerated(client) -> None:
    token, codes, user_id = await owner_with_2fa(client)
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 11 and "0" not in c for c in codes)
    r = await second_step(client, {"backup_code": codes[0]})
    assert r.status_code == 200 and r.json()["access_token"]
    again = await second_step(client, {"backup_code": codes[0]})
    assert again.status_code == 401  # used up
    assert "user.backup_code_used" in await audit_actions()
    async with db.sessionmaker() as s:
        assert await backup_codes.left(s, UUID(user_id)) == 9
    assert (await second_step(client, {"code": "123456", "backup_code": codes[1]})).status_code == 422  # one of them
    wrong = await client.post(f"{PREFIX}/2fa/backup-codes", json={"password": "nope", "backup_code": codes[2]}, headers=bearer(token))
    assert wrong.status_code == 401
    fresh = (await client.post(f"{PREFIX}/2fa/backup-codes", json={"password": PASSWORD, "backup_code": codes[2]}, headers=bearer(token))).json()
    assert len(fresh["codes"]) == 10
    assert (await second_step(client, {"backup_code": codes[1]})).status_code == 401  # the old set is retired
    assert (await second_step(client, {"backup_code": fresh["codes"][0]})).status_code == 200
    assert "user.backup_codes_regenerated" in await audit_actions()


async def test_sessions_listed_current_marked_and_revoked_at_once(client) -> None:
    await make_user(role="cashier")
    first = (await login(client)).json()
    second = (await login(client, ip="10.0.0.2")).json()
    rows = (await client.get(f"{PREFIX}/me/sessions", headers=bearer(second["access_token"]))).json()
    assert len(rows) == 2 and [r["current"] for r in rows] == [True, False]
    other = rows[1]["id"]
    r = await client.post(f"{PREFIX}/me/sessions/{other}/revoke", headers=bearer(second["access_token"]))
    assert r.status_code == 204
    assert (await verify(client, first["access_token"])).status_code == 401  # its access token, at once
    assert (await client.post(f"{PREFIX}/refresh", json={"refresh_token": first["refresh_token"]})).status_code == 401
    assert (await verify(client, second["access_token"])).status_code == 200
    await make_user(phone="012999888", role="cashier")
    theirs = (await login(client, phone="012999888")).json()
    r = await client.post(f"{PREFIX}/me/sessions/{rows[0]['id']}/revoke", headers=bearer(theirs["access_token"]))
    assert r.status_code == 404  # not their session
    assert "user.session_revoked" in await audit_actions()
