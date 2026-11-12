"""Turning 2FA off, a new key, new backup codes, the owner's reset and the server command."""

import asyncio
from uuid import UUID

import pyotp
from sqlalchemy import select

from auth_service import cli
from auth_service.config import get_settings
from auth_service.db import db
from auth_service.models import OutboxEvent, User
from auth_service.services import backup_codes, pins

from .conftest import PASSWORD, PREFIX, as_user, audit_actions, make_user, totp, verify

PHONE = "012345678"
IPS = iter(range(1, 250))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def sign_in(client, phone: str = PHONE, secret: str | None = None, step: int = 0, backup: str | None = None) -> dict:  # noqa: ANN001
    ip = f"10.0.3.{next(IPS)}"  # the login rate limit counts per IP and phone
    r = await client.post(f"{PREFIX}/login", json={"phone": phone, "password": PASSWORD}, headers={"X-Forwarded-For": ip})
    assert r.status_code == 200, r.text
    if r.json().get("mfa_required"):
        proof = {"backup_code": backup} if backup else {"code": totp(secret, step)}
        r = await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": r.json()["mfa_token"], **proof})
        assert r.status_code == 200, r.text
    return r.json()


async def turn_on(client, phone: str = PHONE) -> tuple[str, str, list[str]]:  # noqa: ANN001
    token = (await sign_in(client, phone))["access_token"]
    secret = (await client.post(f"{PREFIX}/2fa/setup", headers=bearer(token))).json()["secret"]
    r = await client.post(f"{PREFIX}/2fa/enable", json={"code": totp(secret)}, headers=bearer(token))
    assert r.status_code == 200, r.text
    return r.json()["access_token"], secret, r.json()["backup_codes"]


async def events(name: str) -> list[dict]:
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.event_type == name))).scalars().all()
        return [r.payload for r in rows]


async def user_row(user_id: UUID) -> User:
    async with db.sessionmaker() as s:
        return await s.get(User, user_id)


async def test_any_user_can_turn_it_on_and_off_with_password_and_code(client) -> None:
    user = await make_user(role="cashier")
    token, secret, codes = await turn_on(client)
    assert len(codes) == 10
    me = (await client.get(f"{PREFIX}/me", headers=await as_user(user))).json()
    assert me["totp_enabled"] is True and me["mfa_required_for_role"] is False
    r = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "code": totp(secret, 1)}, headers=bearer(token))
    assert r.status_code == 204
    row = await user_row(user.id)
    assert row.totp_enabled is False and row.totp_secret_enc is None
    assert "user.2fa_disabled" in await audit_actions()
    alert = (await events("user.2fa_disabled"))[0]
    assert set(alert) == {"user_id", "by", "occurred_at"} and alert["by"] == "self"  # nothing secret
    async with db.sessionmaker() as s:
        assert await backup_codes.left(s, user.id) == 0
    assert (await sign_in(client))["access_token"]  # no second step any more


async def test_disable_refuses_a_wrong_password_or_code_and_counts_them(client) -> None:
    user = await make_user(role="cashier")
    token, secret, _ = await turn_on(client)
    wrong_pw = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": "wrong-one", "code": totp(secret, 1)}, headers=bearer(token))
    assert wrong_pw.status_code == 401 and wrong_pw.json()["code"] == "INVALID_CREDENTIALS"
    wrong_code = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "code": "000000"}, headers=bearer(token))
    assert wrong_code.status_code == 401 and wrong_code.json()["code"] == "INVALID_MFA_CODE"
    wrong_backup = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "backup_code": "AAAAA-BBBBB"}, headers=bearer(token))
    assert wrong_backup.status_code == 401 and wrong_backup.json()["code"] == "INVALID_MFA_CODE"
    assert (await user_row(user.id)).failed_attempts == 3 and (await user_row(user.id)).totp_enabled is True
    neither = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD}, headers=bearer(token))
    assert neither.status_code == 422


async def test_too_many_wrong_codes_lock_the_account_like_login(client) -> None:
    await make_user(role="cashier")
    token, secret, _ = await turn_on(client)
    last = None
    for _ in range(get_settings().lockout_threshold):
        last = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "code": "000000"}, headers=bearer(token))
    assert last.status_code == 423 and last.json()["code"] == "ACCOUNT_LOCKED" and last.json()["details"]["locked_until"]
    right = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "code": totp(secret, 1)}, headers=bearer(token))
    assert right.status_code == 423  # locked: even the right code waits
    assert "user.locked" in await audit_actions()


async def test_a_backup_code_turns_it_off_and_works_once(client) -> None:
    await make_user(role="cashier")
    token, secret, codes = await turn_on(client)
    regen = await client.post(f"{PREFIX}/2fa/backup-codes", json={"password": PASSWORD, "backup_code": codes[0]}, headers=bearer(token))
    assert regen.status_code == 200
    fresh = regen.json()["codes"]
    used = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "backup_code": codes[0]}, headers=bearer(token))
    assert used.status_code == 401  # used, and that whole set is retired
    ok = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "backup_code": fresh[0]}, headers=bearer(token))
    assert ok.status_code == 204


async def test_owner_and_manager_cannot_turn_it_off(client) -> None:
    for role, phone in (("owner", PHONE), ("branch_manager", "012345679")):
        await make_user(role=role, phone=phone)
        token, secret, _ = await turn_on(client, phone)
        r = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "code": totp(secret, 1)}, headers=bearer(token))
        assert r.status_code == 403 and r.json()["code"] == "MFA_REQUIRED_FOR_ROLE"


async def test_turning_off_ends_the_other_sessions_and_keeps_this_one(client) -> None:
    await make_user(role="cashier")
    token, secret, codes = await turn_on(client)
    other = await sign_in(client, backup=codes[0])
    r = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "code": totp(secret, 1)}, headers=bearer(token))
    assert r.status_code == 204
    assert (await verify(client, other["access_token"])).status_code == 401
    assert (await client.post(f"{PREFIX}/refresh", json={"refresh_token": other["refresh_token"]})).status_code == 401
    assert (await verify(client, token)).status_code == 200


async def test_own_reset_keeps_the_old_key_until_the_new_one_is_confirmed(client) -> None:
    user = await make_user(role="branch_manager")
    token, secret, old_codes = await turn_on(client)
    other = await sign_in(client, backup=old_codes[1])
    bad = await client.post(f"{PREFIX}/me/2fa/reset", json={"password": "wrong-one", "code": "000000"}, headers=bearer(token))
    assert bad.status_code == 401
    start = await client.post(f"{PREFIX}/me/2fa/reset", json={"password": PASSWORD, "backup_code": old_codes[0]}, headers=bearer(token))
    assert start.status_code == 200 and start.json()["qr_svg"]
    new = start.json()["secret"]
    assert new != secret
    assert (await user_row(user.id)).totp_enabled is True
    # not confirmed yet: the old key still logs in, the new one does not
    wrong = await client.post(f"{PREFIX}/me/2fa/reset/confirm", json={"code": "000000"}, headers=bearer(token))
    assert wrong.status_code == 401 and wrong.json()["code"] == "INVALID_MFA_CODE"
    assert (await sign_in(client, secret=secret, step=1))["access_token"]
    done = await client.post(f"{PREFIX}/me/2fa/reset/confirm", json={"code": pyotp.TOTP(new).now()}, headers=bearer(token))
    assert done.status_code == 200 and len(done.json()["codes"]) == 10
    row = await user_row(user.id)
    assert row.totp_enabled is True and row.totp_pending_secret_enc is None
    assert (await verify(client, other["access_token"])).status_code == 401  # other sessions ended
    assert (await verify(client, token)).status_code == 200
    assert "user.2fa_reset" in await audit_actions()
    assert (await events("user.2fa_reset"))[0]["by"] == "self"
    step1 = await client.post(f"{PREFIX}/login", json={"phone": PHONE, "password": PASSWORD}, headers={"X-Forwarded-For": "10.0.3.251"})
    old = await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": step1.json()["mfa_token"], "code": totp(secret)})
    assert old.status_code == 401  # the old key is dead
    again = await client.post(f"{PREFIX}/me/2fa/reset/confirm", json={"code": pyotp.TOTP(new).now()}, headers=bearer(token))
    assert again.status_code == 409


async def test_new_backup_codes_need_password_and_code_and_retire_the_old(client) -> None:
    await make_user(role="cashier")
    token, secret, codes = await turn_on(client)
    only_pw = await client.post(f"{PREFIX}/2fa/backup-codes", json={"password": PASSWORD}, headers=bearer(token))
    assert only_pw.status_code == 422
    wrong = await client.post(f"{PREFIX}/2fa/backup-codes", json={"password": PASSWORD, "code": "000000"}, headers=bearer(token))
    assert wrong.status_code == 401
    ok = await client.post(f"{PREFIX}/2fa/backup-codes", json={"password": PASSWORD, "code": totp(secret, 1)}, headers=bearer(token))
    assert ok.status_code == 200 and len(ok.json()["codes"]) == 10
    old = await client.post(f"{PREFIX}/me/2fa/disable", json={"password": PASSWORD, "backup_code": codes[1]}, headers=bearer(token))
    assert old.status_code == 401


async def test_owner_resets_a_users_2fa_with_a_pin(client, redis) -> None:  # noqa: ANN001
    owner = await make_user(role="owner", phone="012000001")
    cashier = await make_user(role="cashier")
    manager = await make_user(role="branch_manager", phone="012000002")
    token, _, _ = await turn_on(client)
    url = f"{PREFIX}/users/{cashier.id}/2fa/reset"
    headers = await as_user(owner)
    missing = await client.post(url, json={}, headers=headers)
    assert missing.status_code == 401 and missing.json()["code"] == "PIN_REQUIRED"
    assert (await client.post(url, json={"pin_token": "nope"}, headers=headers)).json()["code"] == "PIN_INVALID"
    other_action = await pins._issue(redis, owner, "controlled.adjust", "actor", owner.id)
    assert (await client.post(url, json={"pin_token": other_action["pin_token"]}, headers=headers)).json()["code"] == "PIN_INVALID"
    refused = await client.post(url, json={"pin_token": "x"}, headers=await as_user(manager))
    assert refused.status_code == 403  # a manager cannot, even with settings.users
    pin = await pins._issue(redis, owner, "auth.mfa_reset", "actor", owner.id)
    assert (await client.post(url, json={"pin_token": pin["pin_token"]}, headers=headers)).status_code == 204
    row = await user_row(cashier.id)
    assert row.totp_enabled is False and row.totp_secret_enc is None
    assert (await verify(client, token)).status_code == 401  # all the user's sessions ended
    assert "user.2fa_reset" in await audit_actions()
    assert (await events("user.2fa_reset"))[0]["by"] == "owner"
    async with db.sessionmaker() as s:
        assert await backup_codes.left(s, cashier.id) == 0


async def test_a_reset_manager_must_set_it_up_again(client, redis) -> None:  # noqa: ANN001
    owner = await make_user(role="owner", phone="012000001")
    manager = await make_user(role="branch_manager")
    await turn_on(client)
    pin = await pins._issue(redis, owner, "auth.mfa_reset", "actor", owner.id)
    r = await client.post(f"{PREFIX}/users/{manager.id}/2fa/reset", json={"pin_token": pin["pin_token"]}, headers=await as_user(owner))
    assert r.status_code == 204
    assert (await sign_in(client))["mfa_setup_required"] is True


async def test_server_command_resets_an_owner_and_is_audited(client) -> None:
    owner = await make_user(role="owner")
    token, _, _ = await turn_on(client)
    # the real command line, as on the server (main() runs its own event loop)
    assert await asyncio.to_thread(cli.main, ["reset-2fa", "--phone", PHONE]) == 0
    assert (await user_row(owner.id)).totp_enabled is False
    assert (await verify(client, token)).status_code == 401
    assert "user.2fa_reset" in await audit_actions()
    assert (await events("user.2fa_reset"))[0]["by"] == "server"


async def test_server_command_refuses_an_unknown_phone() -> None:
    assert await asyncio.to_thread(cli.main, ["reset-2fa", "--phone", "012999111"]) == 1


async def test_enable_in_the_web_app_keeps_the_refresh_token_out_of_the_body(client) -> None:
    await make_user(role="cashier")
    token = (await sign_in(client))["access_token"]
    secret = (await client.post(f"{PREFIX}/2fa/setup", headers=bearer(token))).json()["secret"]
    r = await client.post(f"{PREFIX}/2fa/enable", json={"code": totp(secret)}, headers={**bearer(token), "X-Refresh-Cookie": "1"})
    assert r.status_code == 200 and "refresh_token" not in r.json()
    assert any(h.startswith("pharmacy_refresh=") for h in r.headers.get_list("set-cookie"))
