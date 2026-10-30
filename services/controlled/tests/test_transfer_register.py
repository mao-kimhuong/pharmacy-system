"""A controlled transfer writes transfer_out at the source and transfer_in at the
destination, each with its witness (through the real inventory app)."""

from uuid import uuid4

import httpx

import inventory_service.main as inventory_main
from inventory_service.services.clients import get_auth as inventory_auth

from .conftest import AUTH, PP1, PP2, PREFIX, add_controlled, idem, receive, relay, user

INV = "/api/inventory/v1"
PERMS = "transfers.request,transfers.approve,transfers.dispatch,transfers.receive,controlled.view"
SOURCE = user("branch_manager", PERMS, (PP1,))
DEST = user("branch_manager", PERMS, (PP2,))


def sign(who: dict, action: str, branch, witness: str) -> dict:  # noqa: ANN001
    return {"pin_token": AUTH.issue(who["X-User-Id"], action, branches=(branch,)),
            "witness_token": AUTH.issue(str(uuid4()), action, "witness", branches=(branch,), name=witness)}  # fmt: skip


async def test_controlled_transfer_reaches_both_registers(client) -> None:
    diaz = await add_controlled()
    await receive(diaz, 50)
    inventory_main.app.dependency_overrides[inventory_auth] = lambda: AUTH
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=inventory_main.app), base_url="http://i") as inv:
            r = await inv.post(f"{INV}/transfers", headers=SOURCE, json={
                "from_branch_id": str(PP1), "to_branch_id": str(PP2), "lines": [{"medicine_id": diaz, "qty_base": 20}]})  # fmt: skip
            t = r.json()
            await inv.post(f"{INV}/transfers/{t['id']}/pick", json={}, headers=SOURCE)
            t = (await inv.post(f"{INV}/transfers/{t['id']}/dispatch", headers={**SOURCE, **idem()},
                                json=sign(SOURCE, "transfers.dispatch", PP1, "Witness A"))).json()  # fmt: skip
            lines = [{"pick_id": p["id"], "qty_received": p["qty_base"]} for p in t["picks"]]
            r = await inv.post(f"{INV}/transfers/{t['id']}/receive", headers={**DEST, **idem()},
                               json={"lines": lines, **sign(DEST, "transfers.receive", PP2, "Witness B")})  # fmt: skip
            assert r.json()["status"] == "closed", r.text
    finally:
        inventory_main.app.dependency_overrides.pop(inventory_auth, None)
    await relay()
    src = (await client.get(f"{PREFIX}/register", params={"branch_id": str(PP1), "medicine_id": diaz},
                            headers=SOURCE)).json()  # fmt: skip
    dst = (await client.get(f"{PREFIX}/register", params={"branch_id": str(PP2), "medicine_id": diaz},
                            headers=DEST)).json()  # fmt: skip
    assert [(e["entry_type"], e["qty_base"], e["balance_after"]) for e in src["entries"]] == [
        ("receive", 50, 50), ("transfer_out", -20, 30)]  # fmt: skip
    assert [(e["entry_type"], e["qty_base"], e["balance_after"], e["witness_name"]) for e in dst["entries"]] == [
        ("transfer_in", 20, 20, "Witness B")]  # fmt: skip
    assert src["entries"][-1]["witness_name"] == "Witness A" and src["chain_valid"] and dst["chain_valid"]
