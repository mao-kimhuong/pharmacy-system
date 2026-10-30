"""The controlled-drug register: entries from movements (once), hash chain and
tamper detection, append-only database, adjust/destroy with PIN + witness,
corrections, reconciliation and discrepancies."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from controlled_service.db import db
from controlled_service.models import Discrepancy, RegisterEntry
from controlled_service.services.reconcile import reconcile

from .conftest import (
    AUTH,
    CASHIER,
    MANAGER,
    PHARMACIST,
    PP1,
    PP2,
    PREFIX,
    add_controlled,
    batch_id,
    clients,
    event,
    idem,
    receive,
    relay,
    user,
)  # fmt: skip


async def register(client, medicine_id: str | None = None, headers=PHARMACIST) -> dict:  # noqa: ANN001
    params = {"branch_id": str(PP1), **({"medicine_id": medicine_id} if medicine_id else {})}
    r = await client.get(f"{PREFIX}/register", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def tokens(action: str, actor: dict = PHARMACIST, witness: str | None = None, role: str = "branch_manager") -> dict:
    return {"pin_token": AUTH.issue(actor["X-User-Id"], action, branches=(PP1,)),
            "witness_token": AUTH.issue(witness or str(uuid4()), action, "witness", branches=(PP1,),
                                        name="Witness Dara", role=role)}  # fmt: skip


async def test_receipt_becomes_an_entry_once_with_running_balance(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 100)
    await receive(diaz, 50, lot="D2")
    assert await relay() == 2
    await relay()  # the same events again
    reg = await register(client, diaz)
    assert [(e["entry_type"], e["qty_base"], e["balance_after"]) for e in reg["entries"]] == [
        ("receive", 100, 100), ("receive", 50, 150)]  # fmt: skip
    assert reg["chain_valid"] and reg["entries"][1]["lot_no"] == "D2"
    assert reg["medicines"][0]["schedule"] == "IV"


async def test_other_medicines_are_not_in_the_register(client) -> None:
    await event("stock.changed", {"movement_id": str(uuid4()), "seq": 1, "branch_id": str(PP1),
                                  "batch_id": str(uuid4()), "medicine_id": str(uuid4()), "type": "in", "delta": 5,
                                  "is_controlled": False})  # fmt: skip
    assert (await register(client))["entries"] == []


async def test_editing_a_past_entry_is_detected(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 100)
    await receive(diaz, 20, lot="D2")
    await relay()
    async with db.engine.begin() as conn:
        await conn.execute(text("SET LOCAL session_replication_role = replica"))  # an attacker with superuser rights
        await conn.execute(text("UPDATE register_entries SET qty_base = 90, balance_after = 90 WHERE lot_no = 'D1'"))
    v = (await client.get(f"{PREFIX}/register/verify", params={"branch_id": str(PP1)}, headers=PHARMACIST)).json()
    assert v["valid"] is False and v["chains"][0]["problem"]
    first = (await register(client, diaz))["entries"][0]["id"]
    assert v["chains"][0]["first_bad_entry_id"] == first
    async with db.sessionmaker() as s:
        result = await reconcile(s, clients())
    assert result["chains_broken"] == 1


async def test_the_database_refuses_update_delete_truncate(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 10)
    await relay()
    for sql in ("UPDATE register_entries SET reason = 'x'", "DELETE FROM register_entries",
                "TRUNCATE register_entries"):  # fmt: skip
        with pytest.raises(DBAPIError, match="append-only"):
            async with db.engine.begin() as conn:
                await conn.execute(text(sql))
    assert len((await register(client))["entries"]) == 1


async def test_destroy_needs_pin_witness_and_method(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 100)
    await relay()
    body = {"branch_id": str(PP1), "batch_id": await batch_id(diaz), "kind": "destroy", "qty_base": 4,
            "reason": "Broken tablets"}  # fmt: skip
    r = await client.post(f"{PREFIX}/entries", json=body, headers={**PHARMACIST, **idem()})
    assert r.status_code == 422 and r.json()["details"]["field"] == "destruction_method"
    body["destruction_method"] = "Crushed with water, witnessed"
    r = await client.post(f"{PREFIX}/entries", json=body, headers={**PHARMACIST, **idem()})
    assert r.status_code == 401 and r.json()["code"] == "PIN_REQUIRED"
    pin = {"pin_token": AUTH.issue(PHARMACIST["X-User-Id"], "controlled.destroy", branches=(PP1,))}
    r = await client.post(f"{PREFIX}/entries", json={**body, **pin}, headers={**PHARMACIST, **idem()})
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_REQUIRED"
    same = tokens("controlled.destroy", witness=PHARMACIST["X-User-Id"])
    r = await client.post(f"{PREFIX}/entries", json={**body, **same}, headers={**PHARMACIST, **idem()})
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"
    wrong_action = tokens("controlled.adjust")
    r = await client.post(f"{PREFIX}/entries", json={**body, **wrong_action}, headers={**PHARMACIST, **idem()})
    assert r.status_code == 401 and r.json()["code"] == "PIN_INVALID"
    r = await client.post(f"{PREFIX}/entries", json={**body, **tokens("controlled.destroy")},
                          headers={**PHARMACIST, **idem()})  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["witness_name"] == "Witness Dara"
    await relay()
    last = (await register(client, diaz))["entries"][-1]
    assert (last["entry_type"], last["qty_base"], last["balance_after"]) == ("destroy", -4, 96)
    assert last["witness_name"] == "Witness Dara" and last["reason"] == "Broken tablets"
    assert (await register(client, diaz))["chain_valid"]


async def test_destroy_needs_a_manager_or_owner_witness_adjust_does_not(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 50)
    await relay()
    batch = await batch_id(diaz)
    destroy = {"branch_id": str(PP1), "batch_id": batch, "kind": "destroy", "qty_base": 2, "reason": "Expired",
               "destruction_method": "Incinerated"}  # fmt: skip
    r = await client.post(f"{PREFIX}/entries", json={**destroy, **tokens("controlled.destroy", role="pharmacist")},
                          headers={**PHARMACIST, **idem()})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"
    assert r.json()["details"]["witness_roles"] == ["branch_manager", "owner"]
    for role in ("branch_manager", "owner"):
        r = await client.post(f"{PREFIX}/entries", json={**destroy, **tokens("controlled.destroy", role=role)},
                              headers={**PHARMACIST, **idem()})  # fmt: skip
        assert r.status_code == 201, r.text
    adjust = {"branch_id": str(PP1), "batch_id": batch, "kind": "adjust_out", "qty_base": 1, "reason": "Miscount"}
    r = await client.post(f"{PREFIX}/entries", json={**adjust, **tokens("controlled.adjust", role="pharmacist")},
                          headers={**PHARMACIST, **idem()})  # fmt: skip
    assert r.status_code == 201, r.text
    await relay()
    assert (await register(client, diaz))["entries"][-1]["balance_after"] == 45


async def test_cashier_and_other_branch_cannot(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 10)
    await relay()
    assert (await client.get(f"{PREFIX}/register", params={"branch_id": str(PP1)}, headers=CASHIER)).status_code == 403
    other = user("pharmacist", "controlled.view,controlled.adjust", (PP2,))
    assert (await client.get(f"{PREFIX}/register", params={"branch_id": str(PP1)}, headers=other)).status_code == 403
    body = {"branch_id": str(PP1), "batch_id": await batch_id(diaz), "kind": "adjust_out", "qty_base": 1,
            "reason": "x", **tokens("controlled.adjust")}  # fmt: skip
    assert (await client.post(f"{PREFIX}/entries", json=body, headers={**other, **idem()})).status_code == 403


async def test_reconciliation_finds_a_difference_and_resolution(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 100)
    await relay()
    async with db.sessionmaker() as s:
        assert (await reconcile(s, clients()))["opened"] == 0
    # stock moves but the register never hears of it (simulated lost entry): sell 10 straight in inventory
    from inventory_service.db import db as inventory_db
    from inventory_service.models import Batch
    from inventory_service.services.movements import apply_movement

    async with inventory_db.sessionmaker() as s:
        batch = await s.get(Batch, (await batch_id(diaz)))
        await apply_movement(s, branch_id=PP1, batch=batch, type="adjust_out", qty_base=-10, ref_type="test",
                             ref_id="lost")  # fmt: skip
        await s.commit()
    async with db.sessionmaker() as s:
        assert (await reconcile(s, clients()))["opened"] == 0  # not relayed yet: the register is behind, skip
    # mark everything up to now as seen, without the entry (as if it was lost)
    await event("stock.changed", {"seq": 10_000, "is_controlled": False, "movement_id": str(uuid4())})
    async with db.sessionmaker() as s:
        assert (await reconcile(s, clients()))["opened"] == 1
    async with db.sessionmaker() as s:
        assert (await reconcile(s, clients()))["opened"] == 0  # still the same one, not a second
    found = (await client.get(f"{PREFIX}/discrepancies", params={"branch_id": str(PP1)}, headers=MANAGER)).json()
    assert [(d["register_qty"], d["stock_qty"], d["difference"]) for d in found] == [(100, 90, -10)]
    r = await client.post(f"{PREFIX}/discrepancies/{found[0]['id']}/resolve", headers=PHARMACIST,
                          json={"reason": "x", **tokens("controlled.resolve")})  # fmt: skip
    assert r.status_code == 403
    r = await client.post(f"{PREFIX}/discrepancies/{found[0]['id']}/resolve", headers=MANAGER, json={
        "reason": "Sale entered on paper only", "correct_register": True, **tokens("controlled.resolve", MANAGER)})  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved" and r.json()["correction_entry_id"]
    last = (await register(client, diaz))["entries"][-1]
    assert (last["entry_type"], last["qty_base"], last["balance_after"]) == ("correction", -10, 90)
    async with db.sessionmaker() as s:
        assert (await reconcile(s, clients()))["opened"] == 0


async def test_open_discrepancy_clears_when_stock_and_register_agree(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 30)
    await event("stock.changed", {"seq": 10_000, "is_controlled": False, "movement_id": str(uuid4())})
    async with db.sessionmaker() as s:
        assert (await reconcile(s, clients()))["opened"] == 1  # stock with no register entry
    await relay()  # the receipt arrives after all
    async with db.sessionmaker() as s:
        assert (await reconcile(s, clients()))["cleared"] == 1
    async with db.sessionmaker() as s:
        assert (await s.execute(select(Discrepancy.status))).scalar_one() == "cleared"


async def test_correction_is_a_new_row_and_old_stays(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 100)
    await relay()
    wrong = (await register(client, diaz))["entries"][0]
    r = await client.post(f"{PREFIX}/entries/correction", headers={**PHARMACIST, **idem()}, json={
        "corrects_entry_id": wrong["id"], "qty_base": 0, "reason": "Lot number was misread on paper",
        **tokens("controlled.adjust")})  # fmt: skip
    assert r.status_code == 201, r.text
    entries = (await register(client, diaz))["entries"]
    assert len(entries) == 2 and entries[0] == wrong and entries[1]["corrects_entry_id"] == wrong["id"]
    async with db.sessionmaker() as s:
        assert (await s.execute(select(RegisterEntry.entry_type).order_by(RegisterEntry.seq))).scalars().all() == [
            "receive", "correction"]  # fmt: skip


async def test_open_balances_for_stock_before_the_register(client) -> None:
    from controlled_service.services.register import open_balances

    diaz = await add_controlled()
    await receive(diaz, 40)  # not relayed: stock the register never saw
    async with db.sessionmaker() as s:
        assert await open_balances(s, clients()) == 1
    async with db.sessionmaker() as s:
        assert await open_balances(s, clients()) == 0
    entries = (await register(client, diaz))["entries"]
    assert [(e["entry_type"], e["balance_after"]) for e in entries] == [("opening", 40)]
