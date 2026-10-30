from uuid import uuid4

import pytest

from auth_service.db import db
from auth_service.services import users as users_service
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError

from .conftest import PASSWORD, PREFIX, add_branch, as_user, audit_actions, login, make_user, verify

NEW = {"name": "Dara", "phone": "077111222", "password": "a-good-password", "role": "cashier"}


async def setup_owner_and_branches():
    b1 = await add_branch(code="PP1")
    b2 = await add_branch(code="PP2")
    owner = await make_user(phone="010000000", role="owner")
    return owner, b1, b2


async def test_owner_creates_a_cashier(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    r = await client.post(
        f"{PREFIX}/users", json={**NEW, "branch_ids": [str(b1)]}, headers=await as_user(owner)
    )
    assert r.status_code == 201
    body = r.json()
    assert body["phone"] == "077111222"
    assert body["branch_ids"] == [str(b1)]
    assert "password" not in str(body)
    assert "user.created" in await audit_actions()
    assert (await login(client, phone="077111222", password="a-good-password")).status_code == 200


async def test_cashier_cannot_manage_users(client) -> None:
    _, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    r = await client.get(f"{PREFIX}/users", headers=await as_user(cashier))
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"
    r = await client.post(
        f"{PREFIX}/users", json={**NEW, "branch_ids": [str(b1)]}, headers=await as_user(cashier)
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    "change,code,status",
    [
        ({"branch_ids": []}, "UNKNOWN_BRANCH", 422),
        ({"branch_ids": [str(uuid4())]}, "UNKNOWN_BRANCH", 422),
        ({"password": "short"}, "WEAK_PASSWORD", 422),
        ({"role": "nope"}, "UNKNOWN_ROLE", 422),
        ({"phone": "abc"}, "VALIDATION_ERROR", 422),
    ],
)
async def test_create_validation(client, change, code, status) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    body = {**NEW, "branch_ids": [str(b1)], **change}
    r = await client.post(f"{PREFIX}/users", json=body, headers=await as_user(owner))
    assert r.status_code == status
    assert r.json()["code"] == code


async def test_inactive_branch_cannot_be_assigned(client) -> None:
    owner, _, _ = await setup_owner_and_branches()
    closed = await add_branch(code="OLD", active=False)
    r = await client.post(
        f"{PREFIX}/users", json={**NEW, "branch_ids": [str(closed)]}, headers=await as_user(owner)
    )
    assert r.json()["code"] == "UNKNOWN_BRANCH"


async def test_duplicate_phone(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    await make_user(phone="077111222", branches=(b1,))
    r = await client.post(
        f"{PREFIX}/users",
        json={**NEW, "phone": "+855 77 111 222", "branch_ids": [str(b1)]},
        headers=await as_user(owner),
    )
    assert r.status_code == 409
    assert r.json()["code"] == "DUPLICATE_PHONE"


async def test_extra_fields_are_rejected(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    r = await client.post(
        f"{PREFIX}/users",
        json={**NEW, "branch_ids": [str(b1)], "is_active": False},
        headers=await as_user(owner),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- branch manager limits


async def manager_setup():
    owner, b1, b2 = await setup_owner_and_branches()
    manager = await make_user(phone="012222222", role="branch_manager", branches=(b1,))
    own_staff = await make_user(phone="013333333", branches=(b1,), name="Own staff")
    other_staff = await make_user(phone="014444444", branches=(b2,), name="Other branch")
    return owner, manager, own_staff, other_staff, b1, b2


async def test_manager_lists_only_own_branch_staff(client) -> None:
    _, manager, own, other, _, _ = await manager_setup()
    r = await client.get(f"{PREFIX}/users", headers=await as_user(manager))
    ids = {u["id"] for u in r.json()["items"]}
    assert str(own.id) in ids
    assert str(other.id) not in ids


async def test_manager_cannot_open_other_branch_staff(client) -> None:
    _, manager, _, other, _, _ = await manager_setup()
    r = await client.get(f"{PREFIX}/users/{other.id}", headers=await as_user(manager))
    assert r.status_code == 404


async def test_manager_creates_cashier_in_own_branch_only(client) -> None:
    _, manager, _, _, b1, b2 = await manager_setup()
    headers = await as_user(manager)
    ok = await client.post(f"{PREFIX}/users", json={**NEW, "branch_ids": [str(b1)]}, headers=headers)
    assert ok.status_code == 201
    other = await client.post(
        f"{PREFIX}/users", json={**NEW, "phone": "077999999", "branch_ids": [str(b2)]}, headers=headers
    )
    assert other.status_code == 403
    assert other.json()["code"] == "BRANCH_FORBIDDEN"


@pytest.mark.parametrize("role", ["owner", "branch_manager"])
async def test_manager_cannot_create_owner_or_manager(client, role) -> None:
    _, manager, _, _, b1, _ = await manager_setup()
    r = await client.post(
        f"{PREFIX}/users", json={**NEW, "role": role, "branch_ids": [str(b1)]}, headers=await as_user(manager)
    )
    assert r.status_code == 403


async def test_manager_cannot_manage_the_owner(client) -> None:
    owner, manager, _, _, _, _ = await manager_setup()
    r = await client.post(
        f"{PREFIX}/users/{owner.id}/deactivate", json={"reason": "x"}, headers=await as_user(manager)
    )
    assert r.status_code == 404


async def test_nobody_changes_their_own_role(client) -> None:
    owner, _, _ = await setup_owner_and_branches()
    r = await client.patch(
        f"{PREFIX}/users/{owner.id}", json={"role": "cashier"}, headers=await as_user(owner)
    )
    assert r.status_code == 403
    assert r.json()["code"] == "CANNOT_CHANGE_SELF"


# ---------------------------------------------------------------- changes end sessions


async def test_deactivate_logs_the_user_out_at_once(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    tokens = (await login(client, phone="011111111")).json()
    r = await client.post(
        f"{PREFIX}/users/{cashier.id}/deactivate",
        json={"reason": "left the job"},
        headers=await as_user(owner),
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert (await verify(client, tokens["access_token"])).status_code == 401
    assert (
        await client.post(f"{PREFIX}/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).status_code == 401
    assert (await login(client, phone="011111111", ip="10.1.1.1")).status_code == 401
    assert "user.deactivated" in await audit_actions()

    back = await client.post(f"{PREFIX}/users/{cashier.id}/activate", headers=await as_user(owner))
    assert back.json()["is_active"] is True
    assert (await login(client, phone="011111111", ip="10.1.1.2")).status_code == 200


async def test_role_change_logs_the_user_out(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    token = (await login(client, phone="011111111")).json()["access_token"]
    r = await client.patch(
        f"{PREFIX}/users/{cashier.id}", json={"role": "pharmacist"}, headers=await as_user(owner)
    )
    assert r.json()["role"] == "pharmacist"
    assert (await verify(client, token)).status_code == 401


async def test_name_change_keeps_the_session(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    token = (await login(client, phone="011111111")).json()["access_token"]
    await client.patch(
        f"{PREFIX}/users/{cashier.id}", json={"name": "New name"}, headers=await as_user(owner)
    )
    assert (await verify(client, token)).status_code == 200


async def test_reset_password_unlocks_and_logs_out(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    token = (await login(client, phone="011111111")).json()["access_token"]
    for i in range(10):
        await login(client, phone="011111111", password="wrong-pass", ip=f"10.9.0.{i}")
    r = await client.post(
        f"{PREFIX}/users/{cashier.id}/reset-password",
        json={"new_password": "new-password-1"},
        headers=await as_user(owner),
    )
    assert r.status_code == 204
    assert (await verify(client, token)).status_code == 401
    assert (
        await login(client, phone="011111111", password="new-password-1", ip="10.9.1.1")
    ).status_code == 200


async def test_audit_log_never_contains_secrets(client) -> None:
    owner, b1, _ = await setup_owner_and_branches()
    await client.post(f"{PREFIX}/users", json={**NEW, "branch_ids": [str(b1)]}, headers=await as_user(owner))
    r = await client.get(f"{PREFIX}/audit-logs", headers=await as_user(owner))
    assert NEW["password"] not in r.text
    assert "password_hash" not in r.text


async def test_last_owner_is_protected() -> None:
    owner = await make_user(phone="010000000", role="owner")
    other_owner = CurrentUser(
        id=uuid4(), role="owner", branch_ids=frozenset(), is_pharmacist=False, permissions=frozenset({"*"})
    )
    async with db.sessionmaker() as session:
        with pytest.raises(AppError) as err:
            await users_service.set_active(session, None, other_owner, owner.id, False, "x", None)  # type: ignore[arg-type]
    assert err.value.code == "LAST_OWNER"


# ---------------------------------------------------------------- own profile


async def test_me_shows_permissions_and_menu(client) -> None:
    _, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    r = await client.get(f"{PREFIX}/me", headers=await as_user(cashier))
    body = r.json()
    assert "pos.sell" in body["permissions"]
    keys = {m["key"] for m in body["menu"]}
    assert "pos" in keys
    assert "user" not in keys  # no settings.users
    assert body["has_pin"] is False


async def test_set_own_pin(client) -> None:
    _, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    headers = await as_user(cashier)
    bad = await client.put(f"{PREFIX}/me/pin", json={"password": PASSWORD, "pin": "12a4"}, headers=headers)
    assert bad.status_code == 422
    wrong_pw = await client.put(
        f"{PREFIX}/me/pin", json={"password": "nope-nope", "pin": "1234"}, headers=headers
    )
    assert wrong_pw.status_code == 401
    ok = await client.put(f"{PREFIX}/me/pin", json={"password": PASSWORD, "pin": "1234"}, headers=headers)
    assert ok.status_code == 204
    assert (await client.get(f"{PREFIX}/me", headers=headers)).json()["has_pin"] is True


async def test_change_own_password_ends_sessions(client) -> None:
    _, b1, _ = await setup_owner_and_branches()
    cashier = await make_user(phone="011111111", branches=(b1,))
    token = (await login(client, phone="011111111")).json()["access_token"]
    r = await client.post(
        f"{PREFIX}/me/password",
        json={"current_password": PASSWORD, "new_password": "brand-new-pass"},
        headers=await as_user(cashier),
    )
    assert r.status_code == 204
    assert (await verify(client, token)).status_code == 401
    assert (
        await login(client, phone="011111111", password="brand-new-pass", ip="10.2.2.2")
    ).status_code == 200


async def test_owner_resets_a_lost_2fa(client) -> None:
    import pyotp

    owner, b1, _ = await setup_owner_and_branches()
    manager = await make_user(
        phone="012222222", role="branch_manager", branches=(b1,), totp_secret=pyotp.random_base32()
    )
    r = await client.post(f"{PREFIX}/users/{manager.id}/2fa/reset", headers=await as_user(owner))
    assert r.status_code == 204
    data = (await login(client, phone="012222222")).json()
    assert data["mfa_setup_required"] is True  # sets it up again


async def test_user_events_carry_name_and_pharmacist_flag_but_no_secrets(client) -> None:
    import json

    from sqlalchemy import text

    from auth_service.cli import republish

    owner, b1, _ = await setup_owner_and_branches()
    r = await client.post(f"{PREFIX}/users", headers=await as_user(owner),
                          json={**NEW, "branch_ids": [str(b1)], "is_pharmacist": True})  # fmt: skip
    async with db.engine.connect() as conn:
        rows = (await conn.execute(text("SELECT event_type, payload FROM outbox ORDER BY seq"))).all()
    payload = next(p if isinstance(p, dict) else json.loads(p) for t, p in rows if t == "user.created")
    assert payload == {"user_id": r.json()["id"], "name": "Dara", "role": "cashier", "is_pharmacist": True,
                       "is_active": True, "branch_ids": [str(b1)]}  # fmt: skip
    assert await republish() == 2  # owner + Dara
