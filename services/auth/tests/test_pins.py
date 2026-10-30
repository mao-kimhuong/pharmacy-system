"""PIN step-up: one-time tokens per action, witnesses, lockout, renamed keys."""

from sqlalchemy import delete, insert, select

from auth_service.db import db
from auth_service.models import Permission, RolePermission
from auth_service.services.catalog_sync import sync_catalog
from auth_service.services.passwords import hash_password

from .conftest import B1, B2, PREFIX, add_branch, as_user, audit_actions, make_user

TOKEN = "test-service-token-0123456789abcdef"


async def pharmacist(phone: str = "012111111", pin: str | None = "4321", branches=(B1,), role="pharmacist"):  # noqa: ANN001, ANN201
    user = await make_user(phone=phone, role=role, branches=branches, is_pharmacist=True, name=f"P {phone}")
    if pin:
        async with db.sessionmaker() as s, s.begin():
            (await s.get(type(user), user.id)).pin_hash = hash_password(pin)
    return user


async def consume(client, token: str, action: str, kind: str = "actor", acting=None):  # noqa: ANN001, ANN201
    headers = {"X-Service-Token": TOKEN, "X-Service-Name": "controlled"}
    if acting:
        headers["X-Acting-User-Id"] = str(acting.id)
    return await client.post("/internal/v1/pin-tokens/consume", json={"token": token, "action": action, "kind": kind},
                             headers=headers)  # fmt: skip


async def test_pin_token_works_once_and_only_for_its_action(client, monkeypatch) -> None:
    from auth_service.config import get_settings

    monkeypatch.setattr(get_settings(), "service_token", TOKEN)
    await add_branch(B1)
    user = await pharmacist()
    r = await client.post(f"{PREFIX}/pin/verify", json={"pin": "4321", "action": "controlled.dispense"},
                          headers=await as_user(user))  # fmt: skip
    assert r.status_code == 200, r.text
    token = r.json()["pin_token"]
    wrong_action = await consume(client, token, "controlled.adjust", acting=user)
    assert wrong_action.status_code == 401 and wrong_action.json()["code"] == "PIN_INVALID"
    # the failed try used the token up as well
    assert (await consume(client, token, "controlled.dispense", acting=user)).status_code == 401
    token = (await client.post(f"{PREFIX}/pin/verify", json={"pin": "4321", "action": "controlled.dispense"},
                               headers=await as_user(user))).json()["pin_token"]  # fmt: skip
    ok = await consume(client, token, "controlled.dispense", acting=user)
    assert ok.status_code == 200 and ok.json()["user_id"] == str(user.id) and ok.json()["is_pharmacist"]
    assert "controlled.dispense" in ok.json()["permissions"]
    assert (await consume(client, token, "controlled.dispense", acting=user)).status_code == 401  # used
    assert (await consume(client, "x" * 20, "controlled.dispense")).status_code == 401
    assert (await client.post("/internal/v1/pin-tokens/consume", json={"token": token, "action": "a.b",
                                                                       "kind": "actor"})).status_code == 401  # fmt: skip


async def test_five_wrong_pins_lock_the_pin(client) -> None:
    user = await pharmacist()
    headers = await as_user(user)
    for left in (4, 3, 2, 1):
        r = await client.post(f"{PREFIX}/pin/verify", json={"pin": "0000", "action": "controlled.dispense"},
                              headers=headers)  # fmt: skip
        assert r.status_code == 401 and r.json()["details"]["attempts_left"] == left
    r = await client.post(f"{PREFIX}/pin/verify", json={"pin": "0000", "action": "controlled.dispense"},
                          headers=headers)  # fmt: skip
    assert r.status_code == 423 and r.json()["code"] == "PIN_LOCKED"
    r = await client.post(f"{PREFIX}/pin/verify", json={"pin": "4321", "action": "controlled.dispense"},
                          headers=headers)  # fmt: skip
    assert r.status_code == 423  # the right PIN does not help while locked
    assert "user.pin_locked" in await audit_actions()


async def test_no_pin_set(client) -> None:
    user = await pharmacist(pin=None)
    r = await client.post(f"{PREFIX}/pin/verify", json={"pin": "1234", "action": "controlled.dispense"},
                          headers=await as_user(user))  # fmt: skip
    assert r.status_code == 401 and r.json()["code"] == "PIN_REQUIRED"


async def test_witness_is_another_person_of_the_branch(client, monkeypatch) -> None:
    from auth_service.config import get_settings

    monkeypatch.setattr(get_settings(), "service_token", TOKEN)
    actor = await pharmacist()
    other = await pharmacist("012222222", "8765")
    far = await pharmacist("012333333", "1111", branches=(B2,))
    headers = await as_user(actor)
    r = await client.post(f"{PREFIX}/pin/witness", headers=headers,
                          json={"witness_user_id": str(actor.id), "pin": "4321", "action": "controlled.adjust"})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"
    r = await client.post(f"{PREFIX}/pin/witness", headers=headers,
                          json={"witness_user_id": str(far.id), "pin": "1111", "action": "controlled.adjust"})  # fmt: skip
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/pin/witness", headers=headers,
                          json={"witness_user_id": str(other.id), "pin": "8765", "action": "controlled.adjust"})  # fmt: skip
    assert r.status_code == 200 and r.json()["name"] == "P 012222222"
    token = r.json()["pin_token"]
    assert (await consume(client, token, "controlled.adjust", "actor", acting=actor)).status_code == 401
    token = (await client.post(f"{PREFIX}/pin/witness", headers=headers, json={
        "witness_user_id": str(other.id), "pin": "8765", "action": "controlled.adjust"})).json()["pin_token"]  # fmt: skip
    ok = await consume(client, token, "controlled.adjust", "witness", acting=actor)
    assert ok.status_code == 200 and ok.json()["user_id"] == str(other.id)
    listed = await client.get(f"{PREFIX}/pin/witnesses", params={"branch_id": str(B1)}, headers=headers)
    assert [w["name"] for w in listed.json()] == ["P 012222222"]


async def test_new_and_renamed_keys_reach_existing_roles() -> None:
    async with db.sessionmaker() as s, s.begin():
        # an older stack: pharmacists had pos.dispense_controlled, controlled.dispense did not exist yet
        await s.execute(insert(Permission).values(key="pos.dispense_controlled", group="Sales", label="old", sort=0))
        await s.execute(insert(RolePermission).values(role_key="pharmacist", permission_key="pos.dispense_controlled"))
        await s.execute(delete(RolePermission).where(RolePermission.permission_key.in_(
            ["controlled.dispense", "inventory.shrinkage"])))  # fmt: skip
        await s.execute(delete(Permission).where(Permission.key.in_(["controlled.dispense", "inventory.shrinkage"])))
    await sync_catalog()
    async with db.sessionmaker() as s:
        keys = set((await s.execute(select(RolePermission.permission_key).where(
            RolePermission.role_key == "pharmacist"))).scalars())  # fmt: skip
        assert (await s.get(Permission, "pos.dispense_controlled")) is None
    assert {"controlled.dispense", "inventory.shrinkage"} <= keys and "pos.dispense_controlled" not in keys


async def test_a_later_default_is_given_once_and_a_removal_stays() -> None:
    from auth_service.models import AppliedGrant

    async with db.sessionmaker() as s, s.begin():
        await s.execute(delete(AppliedGrant))
        await s.execute(delete(RolePermission).where(RolePermission.role_key == "pharmacist",
                                                     RolePermission.permission_key == "controlled.adjust"))  # fmt: skip
    await sync_catalog()  # an existing stack upgrading: pharmacists get controlled.adjust once

    async def has() -> bool:
        async with db.sessionmaker() as s:
            return (await s.get(RolePermission, ("pharmacist", "controlled.adjust"))) is not None

    assert await has()
    async with db.sessionmaker() as s, s.begin():  # the owner takes it away again
        await s.execute(delete(RolePermission).where(RolePermission.role_key == "pharmacist",
                                                     RolePermission.permission_key == "controlled.adjust"))  # fmt: skip
    await sync_catalog()
    assert not await has()
