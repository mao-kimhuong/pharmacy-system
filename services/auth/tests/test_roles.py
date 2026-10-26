import pyotp

from auth_service.services.catalog_sync import sync_catalog

from .conftest import PREFIX, add_branch, as_user, audit_actions, login, make_user, verify


async def owner_headers():
    owner = await make_user(phone="010000000", role="owner")
    return await as_user(owner)


async def test_permission_catalog(client) -> None:
    r = await client.get(f"{PREFIX}/permissions", headers=await owner_headers())
    keys = {p["key"] for p in r.json()}
    assert {"pos.sell", "settings.users", "finance.cost_profit"} <= keys


async def test_built_in_roles_and_defaults(client) -> None:
    roles = {r["key"]: r for r in (await client.get(f"{PREFIX}/roles", headers=await owner_headers())).json()}
    assert set(roles) >= {"owner", "branch_manager", "pharmacist", "cashier"}
    assert roles["owner"]["all_permissions"] is True
    assert "pos.dispense_rx" in roles["pharmacist"]["permissions"]
    assert "pos.dispense_rx" not in roles["cashier"]["permissions"]
    assert "finance.cost_profit" not in roles["branch_manager"]["permissions"]  # "if granted"
    assert "settings.roles" not in roles["branch_manager"]["permissions"]


async def test_create_custom_role_and_use_it(client) -> None:
    headers = await owner_headers()
    r = await client.post(
        f"{PREFIX}/roles",
        json={"key": "senior_cashier", "name": "Senior cashier", "permissions": ["pos.sell", "sales.cancel"]},
        headers=headers,
    )
    assert r.status_code == 201
    assert r.json()["permissions"] == ["pos.sell", "sales.cancel"]
    assert "role.created" in await audit_actions()

    b1 = await add_branch()
    await make_user(phone="011111111", role="senior_cashier", branches=(b1,))
    token = (await login(client, phone="011111111")).json()["access_token"]
    perms = (await verify(client, token)).headers["x-permissions"].split(",")
    assert perms == ["pos.sell", "sales.cancel"]


async def test_role_validation(client) -> None:
    headers = await owner_headers()
    bad_perm = await client.post(
        f"{PREFIX}/roles", json={"key": "x_role", "name": "X", "permissions": ["fly.plane"]}, headers=headers
    )
    assert bad_perm.status_code == 422
    assert bad_perm.json()["code"] == "UNKNOWN_PERMISSION"
    bad_key = await client.post(f"{PREFIX}/roles", json={"key": "Bad Key", "name": "X"}, headers=headers)
    assert bad_key.status_code == 422
    dup = await client.post(f"{PREFIX}/roles", json={"key": "cashier", "name": "X"}, headers=headers)
    assert dup.status_code == 409


async def test_owner_role_cannot_be_edited(client) -> None:
    r = await client.patch(f"{PREFIX}/roles/owner", json={"permissions": []}, headers=await owner_headers())
    assert r.status_code == 409
    assert r.json()["code"] == "ROLE_NOT_EDITABLE"


async def test_built_in_role_cannot_be_removed(client) -> None:
    r = await client.post(f"{PREFIX}/roles/cashier/deactivate", headers=await owner_headers())
    assert r.status_code == 409


async def test_role_in_use_cannot_be_removed(client) -> None:
    headers = await owner_headers()
    await client.post(
        f"{PREFIX}/roles",
        json={"key": "helper", "name": "Helper", "permissions": ["pos.sell"]},
        headers=headers,
    )
    b1 = await add_branch()
    await make_user(phone="011111111", role="helper", branches=(b1,))
    r = await client.post(f"{PREFIX}/roles/helper/deactivate", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "ROLE_IN_USE"


async def test_edited_permissions_apply_at_next_refresh(client) -> None:
    headers = await owner_headers()
    b1 = await add_branch()
    await make_user(phone="011111111", role="cashier", branches=(b1,))
    first = (await login(client, phone="011111111")).json()
    await client.patch(f"{PREFIX}/roles/cashier", json={"permissions": ["pos.sell"]}, headers=headers)
    refreshed = (
        await client.post(f"{PREFIX}/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()
    assert (await verify(client, refreshed["access_token"])).headers["x-permissions"] == "pos.sell"


async def test_owner_edits_survive_a_restart(client) -> None:
    headers = await owner_headers()
    await client.patch(f"{PREFIX}/roles/cashier", json={"permissions": ["pos.sell"]}, headers=headers)
    await sync_catalog()  # what happens at every start
    roles = {r["key"]: r for r in (await client.get(f"{PREFIX}/roles", headers=headers)).json()}
    assert roles["cashier"]["permissions"] == ["pos.sell"]


async def test_manager_cannot_edit_roles(client) -> None:
    b1 = await add_branch()
    manager = await make_user(
        phone="012222222", role="branch_manager", branches=(b1,), totp_secret=pyotp.random_base32()
    )
    r = await client.post(
        f"{PREFIX}/roles", json={"key": "x_role", "name": "X"}, headers=await as_user(manager)
    )
    assert r.status_code == 403


async def test_manager_cannot_give_a_role_with_more_power(client) -> None:
    headers = await owner_headers()
    await client.post(
        f"{PREFIX}/roles",
        json={"key": "profit_viewer", "name": "Profit viewer", "permissions": ["finance.cost_profit"]},
        headers=headers,
    )
    b1 = await add_branch()
    manager = await make_user(phone="012222222", role="branch_manager", branches=(b1,))
    r = await client.post(
        f"{PREFIX}/users",
        json={
            "name": "X",
            "phone": "077000111",
            "password": "good-password",
            "role": "profit_viewer",
            "branch_ids": [str(b1)],
        },
        headers=await as_user(manager),
    )
    assert r.status_code == 403
