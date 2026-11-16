"""T2: shrinkage and transfer requests decided on Telegram (/internal/v1/.../decide as the user who tapped): the same
rules as the app, the User Log says via telegram, never for controlled medicines; the request event carries a value."""

from uuid import UUID, uuid4

from .conftest import INTERNAL, PP1, PP2, PREFIX, add_product, event, goods_received, idem, outbox, user

PERMS = "inventory.view,inventory.shrinkage,transfers.request,transfers.approve"


def actor(role: str = "branch_manager", perms: str = "inventory.shrinkage_approve,transfers.approve",
          branches: tuple[UUID, ...] = (PP1,)) -> dict:  # fmt: skip
    return {"user_id": str(uuid4()), "name": "Dara", "role": role, "branch_ids": [str(b) for b in branches],
            "permissions": perms.split(",")}  # fmt: skip


async def stocked(sku: str = "PARA500", controlled: str | None = None) -> dict:
    product = await add_product(sku, controlled=controlled)
    await event("goods.received", goods_received(product, [("L1", "2028-01-31", 1000, "0.2000")]))
    return product


async def pending_shrinkage(client, product: dict, who: dict) -> dict:  # noqa: ANN001
    batch = (await client.get(f"{PREFIX}/stock", params={"branch_id": str(PP1)}, headers=who)).json()
    batch_id = next(i for i in batch["items"] if i["medicine_id"] == product["id"])["batches"][0]["batch_id"]
    r = await client.post(f"{PREFIX}/shrinkages", headers={**who, **idem()}, json={
        "branch_id": str(PP1), "batch_id": batch_id, "qty_base": 300, "reason": "expired"})  # 60 USD: pending  # fmt: skip
    assert r.json()["status"] == "pending_approval", r.text
    return r.json()


async def decide(client, path: str, body: dict):  # noqa: ANN001, ANN201
    return await client.post(f"/internal/v1/{path}/decide", json=body, headers=INTERNAL)


async def test_shrinkage_approved_on_telegram_follows_the_app_rules(client) -> None:
    maker = user("pharmacist", PERMS)
    s = await pending_shrinkage(client, await stocked(), maker)
    assert (await client.post(f"/internal/v1/shrinkages/{s['id']}/decide", json={
        "decision": "approve", "actor": actor()})).status_code == 401  # a service token only  # fmt: skip
    own = actor(perms="inventory.shrinkage_approve")
    own["user_id"] = maker["X-User-Id"]
    assert (await decide(client, f"shrinkages/{s['id']}", {"decision": "approve", "actor": own})).status_code == 403
    no_perm = actor(perms="inventory.view")
    assert (await decide(client, f"shrinkages/{s['id']}", {"decision": "approve", "actor": no_perm})).status_code == 403
    other_branch = actor(branches=(PP2,))
    assert (await decide(client, f"shrinkages/{s['id']}", {"decision": "approve", "actor": other_branch})).status_code == 404
    r = await decide(client, f"shrinkages/{s['id']}", {"decision": "approve", "actor": actor()})
    assert r.status_code == 200 and r.json() == {"status": "posted", "number": s["number"]}
    again = await decide(client, f"shrinkages/{s['id']}", {"decision": "reject", "actor": actor()})
    assert again.status_code == 409 and again.json()["code"] == "SHRINKAGE_STATE"  # only the first decision
    log = [p for t, p in await outbox() if t == "audit.recorded" and p["action"] == "shrinkage.approved"][-1]
    assert log["after"]["via"] == "telegram"


async def test_shrinkage_rejected_on_telegram_and_controlled_never(client, monkeypatch) -> None:
    maker = user("pharmacist", PERMS)
    s = await pending_shrinkage(client, await stocked(), maker)
    r = await decide(client, f"shrinkages/{s['id']}", {"decision": "reject", "actor": actor(), "reason": "Rejected on Telegram by Dara"})
    assert r.json()["status"] == "rejected"
    log = [p for t, p in await outbox() if t == "audit.recorded" and p["action"] == "shrinkage.rejected"][-1]
    assert log["after"] == {"number": s["number"], "reason": "Rejected on Telegram by Dara", "via": "telegram"}
    from inventory_service.db import db
    from inventory_service.models import Shrinkage

    async with db.sessionmaker() as session:  # a controlled one (made pending here: its PIN path is tested in S5)
        row = await session.get(Shrinkage, UUID(s["id"]))
        row.status, row.is_controlled = "pending_approval", True
        await session.commit()
    r = await decide(client, f"shrinkages/{s['id']}", {"decision": "approve", "actor": actor()})
    assert r.status_code == 403 and "in the app" in r.json()["message"]


async def test_transfer_request_has_a_value_and_is_decided_on_telegram(client) -> None:
    para = await stocked()
    dest = user("branch_manager", PERMS, (PP2,))
    r = await client.post(f"{PREFIX}/transfer-requests", headers=dest, json={
        "from_branch_id": str(PP1), "to_branch_id": str(PP2), "lines": [{"medicine_id": para["id"], "qty_base": 40}]})  # fmt: skip
    req = r.json()
    created = [p for t, p in await outbox() if t == "transfer_request.created"][-1]
    assert (created["value"], created["has_controlled"]) == ("8.00", False)  # 40 × 0.20
    assert created["requested_by"] == dest["X-User-Id"]
    dest_mgr = actor(branches=(PP2,))
    assert (await decide(client, f"transfer-requests/{req['id']}", {"decision": "approve", "actor": dest_mgr})).status_code == 403
    r = await decide(client, f"transfer-requests/{req['id']}", {"decision": "approve", "actor": actor()})
    assert r.status_code == 200 and r.json()["number"].startswith("PP1-TR-")
    approved = [p for t, p in await outbox() if t == "transfer_request.approved"][-1]
    assert approved["via"] == "telegram"
    ctl = await stocked("DIAZ5", controlled="IV")
    req = (await client.post(f"{PREFIX}/transfer-requests", headers=dest, json={
        "from_branch_id": str(PP1), "to_branch_id": str(PP2), "lines": [{"medicine_id": ctl["id"], "qty_base": 5}]})).json()  # fmt: skip
    assert [p for t, p in await outbox() if t == "transfer_request.created"][-1]["has_controlled"] is True
    r = await decide(client, f"transfer-requests/{req['id']}", {"decision": "approve", "actor": actor()})
    assert r.status_code == 403
    r = await decide(client, f"transfer-requests/{req['id']}", {"decision": "reject", "actor": actor()})
    assert r.status_code == 403  # controlled: neither way on Telegram
