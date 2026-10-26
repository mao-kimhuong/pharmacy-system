from uuid import UUID, uuid4

import pytest

from .conftest import CASHIER_PERMS, MANAGER_PERMS, OWNER, PREFIX, create, outbox, user


async def test_owner_creates_a_branch_with_default_settings(client) -> None:
    branch = await create(client, code="pp1", address="St 271, Phnom Penh")
    assert branch["code"] == "PP1"  # upper-cased
    assert branch["is_active"] is True
    settings = (await client.get(f"{PREFIX}/branches/{branch['id']}/settings", headers=OWNER)).json()
    assert settings["expiry_alert_days"] == [180, 90, 30]
    assert settings["price_override_enabled"] is False


async def test_creating_a_branch_sends_events_for_other_services(client) -> None:
    branch = await create(client)
    events = await outbox()
    types = [t for t, _ in events]
    assert types == ["branch.created", "audit.recorded"]
    payload = events[0][1]
    assert payload["branch_id"] == branch["id"]
    assert {"code", "name_en", "is_active"} <= set(payload)
    audit = events[1][1]
    assert audit["action"] == "branch.created" and audit["service"] == "branch"


@pytest.mark.parametrize("code", ["A", "TOO-LONG-CODE", "P P1", "ពព"])
async def test_bad_codes_are_refused(client, code) -> None:
    r = await client.post(
        f"{PREFIX}/branches", json={"code": code, "name_km": "x", "name_en": "x"}, headers=OWNER
    )
    assert r.status_code == 422


async def test_code_is_unique(client) -> None:
    await create(client, code="PP1")
    r = await client.post(
        f"{PREFIX}/branches", json={"code": "pp1", "name_km": "x", "name_en": "x"}, headers=OWNER
    )
    assert r.status_code == 409
    assert r.json()["code"] == "DUPLICATE_CODE"


async def test_code_cannot_be_changed(client) -> None:
    branch = await create(client)
    r = await client.patch(f"{PREFIX}/branches/{branch['id']}", json={"code": "XX9"}, headers=OWNER)
    assert r.status_code == 422


async def test_edit_records_only_changed_fields(client) -> None:
    branch = await create(client)
    r = await client.patch(f"{PREFIX}/branches/{branch['id']}", json={"phone": "023 999 999"}, headers=OWNER)
    assert r.json()["phone"] == "023 999 999"
    audit = [p for t, p in await outbox() if t == "audit.recorded"][-1]
    assert audit["action"] == "branch.updated"
    assert audit["before"] == {"phone": ""} and audit["after"] == {"phone": "023 999 999"}


async def test_staff_see_only_their_branches(client) -> None:
    b1 = await create(client, code="PP1")
    await create(client, code="PP2")
    cashier = user("cashier", (UUID(b1["id"]),), CASHIER_PERMS)
    listed = (await client.get(f"{PREFIX}/branches", headers=cashier)).json()
    assert [b["code"] for b in listed] == ["PP1"]
    assert len((await client.get(f"{PREFIX}/branches", headers=OWNER)).json()) == 2


async def test_other_branches_look_like_not_found(client) -> None:
    await create(client, code="PP1")
    b2 = await create(client, code="PP2")
    cashier = user("cashier", (uuid4(),), CASHIER_PERMS)
    assert (await client.get(f"{PREFIX}/branches/{b2['id']}", headers=cashier)).status_code == 404


async def test_only_settings_branches_can_create(client) -> None:
    manager = user("branch_manager", (uuid4(),), MANAGER_PERMS)
    r = await client.post(
        f"{PREFIX}/branches", json={"code": "PP9", "name_km": "x", "name_en": "x"}, headers=manager
    )
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"


async def test_deactivate_and_activate(client) -> None:
    branch = await create(client)
    r = await client.post(
        f"{PREFIX}/branches/{branch['id']}/deactivate", json={"reason": "closed"}, headers=OWNER
    )
    assert r.json()["is_active"] is False
    assert (await client.get(f"{PREFIX}/branches", headers=OWNER)).json() == []
    with_inactive = (
        await client.get(f"{PREFIX}/branches", params={"include_inactive": True}, headers=OWNER)
    ).json()
    assert len(with_inactive) == 1
    types = [t for t, _ in await outbox()]
    assert "branch.deactivated" in types
    r = await client.post(f"{PREFIX}/branches/{branch['id']}/activate", headers=OWNER)
    assert r.json()["is_active"] is True


async def test_deactivate_needs_a_reason(client) -> None:
    branch = await create(client)
    assert (
        await client.post(f"{PREFIX}/branches/{branch['id']}/deactivate", json={}, headers=OWNER)
    ).status_code == 422


# ---------------------------------------------------------------- settings


async def test_manager_edits_own_branch_settings(client) -> None:
    branch = await create(client)
    manager = user("branch_manager", (UUID(branch["id"]),), MANAGER_PERMS)
    r = await client.put(
        f"{PREFIX}/branches/{branch['id']}/settings",
        json={"expiry_alert_days": [30, 90, 90, 60], "receipt_header": "Thank you"},
        headers=manager,
    )
    assert r.status_code == 200
    assert r.json()["expiry_alert_days"] == [90, 60, 30]  # sorted, duplicates removed
    assert r.json()["receipt_header"] == "Thank you"


async def test_manager_cannot_edit_another_branch(client) -> None:
    branch = await create(client)
    manager = user("branch_manager", (uuid4(),), MANAGER_PERMS)
    r = await client.put(
        f"{PREFIX}/branches/{branch['id']}/settings", json={"receipt_header": "x"}, headers=manager
    )
    assert r.status_code == 403


async def test_cashier_cannot_edit_settings(client) -> None:
    branch = await create(client)
    cashier = user("cashier", (UUID(branch["id"]),), CASHIER_PERMS)
    r = await client.put(
        f"{PREFIX}/branches/{branch['id']}/settings", json={"receipt_header": "x"}, headers=cashier
    )
    assert r.status_code == 403


@pytest.mark.parametrize("days", [[], [0], [1000], [1, 2, 3, 4, 5, 6]])
async def test_bad_alert_days(client, days) -> None:
    branch = await create(client)
    r = await client.put(
        f"{PREFIX}/branches/{branch['id']}/settings", json={"expiry_alert_days": days}, headers=OWNER
    )
    assert r.status_code == 422


async def test_not_logged_in_is_401(client) -> None:
    assert (await client.get(f"{PREFIX}/branches")).status_code == 401
