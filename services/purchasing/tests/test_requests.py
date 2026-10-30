"""Purchase requests: ask → approve / reject → a PO group (one PO per branch,
one group number) or a transfer from another branch; progress follows the PO
receipts and the transfer events (each applied once)."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text

import inventory_service.main as inventory_main
from inventory_service.db import db as inventory_db
from inventory_service.models import OutboxEvent as InventoryOutbox
from inventory_service.models import ProcessedMessage as InventoryProcessed
from inventory_service.services.events import handle_event as inventory_handle
from pharmacy_shared.consumer import process_message
from pharmacy_shared.internal import InternalClient
from purchasing_service.db import db
from purchasing_service.main import app
from purchasing_service.models import ProcessedMessage
from purchasing_service.services.clients import get_inventory
from purchasing_service.services.events import handle_event

from .conftest import (
    OWNER,
    PP1,
    PP2,
    PREFIX,
    SERVICE_TOKEN,
    add_product,
    create_supplier,
    outbox,
    receive,
    user,
)

ASKER = user("pharmacist", "purchasing.request", (PP1,))
ASKER2 = user("pharmacist", "purchasing.request", (PP2,))
APPROVER = user("branch_manager", "purchasing.request,purchasing.request_approve,purchasing.order", (PP1,))
INV = "/api/inventory/v1"


@pytest.fixture
async def inventory():  # noqa: ANN201
    """The real inventory app, with an empty database and both branches."""
    async with inventory_db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE reservation_lines, reservations, quarantine_entries, movements, stock, batches, stock_ins,"
            " product_pack_units, products, known_branches, known_suppliers, processed_messages, outbox, shrinkages,"
            " shelf_locations, branch_settings, doc_sequences, transfer_discrepancies, transfer_picks, transfer_lines,"
            " transfers, transfer_request_lines, transfer_requests CASCADE"))  # fmt: skip
    for bid, code in ((PP1, "PP1"), (PP2, "PP2")):
        await inv_event("branch.created", {"branch_id": str(bid), "code": code, "name_km": "", "name_en": code,
                                           "is_active": True})  # fmt: skip
    client = InternalClient("http://inventory", "purchasing", SERVICE_TOKEN,
                            transport=httpx.ASGITransport(app=inventory_main.app))  # fmt: skip
    app.dependency_overrides[get_inventory] = lambda: client
    yield
    app.dependency_overrides.pop(get_inventory, None)
    await inventory_db.dispose()
    await inventory_main.app.state.redis.close()


async def inv_event(event_type: str, payload: dict) -> None:
    await process_message(inventory_db, InventoryProcessed, inventory_handle, uuid4(), event_type, payload)


async def relay_transfers() -> None:
    """transfer.* from inventory's outbox → purchasing (outbox id = message id)."""
    async with inventory_db.sessionmaker() as s:
        rows = (await s.execute(select(InventoryOutbox).where(InventoryOutbox.event_type.like("transfer.%"))
                                .order_by(InventoryOutbox.seq))).scalars().all()  # fmt: skip
    for row in rows:
        await process_message(db, ProcessedMessage, handle_event, row.id, row.event_type, row.payload)


async def ask(client, product: dict, qty: int = 200, headers=ASKER, branch=PP1) -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/purchase-requests", headers=headers, json={
        "branch_id": str(branch), "lines": [{"medicine_id": product["id"], "qty_base": qty,
                                             "reason": "Low stock", "needed_by": "2026-11-10"}]})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def test_ask_approve_reject_and_who_may(client) -> None:
    para = await add_product("PARA500")
    pr = await ask(client, para)
    assert pr["number"] == "PP1-PR-2026-000001" and pr["status"] == "submitted"
    r = await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/approve", headers=ASKER)
    assert r.status_code == 403
    other = user("branch_manager", "purchasing.request_approve", (PP2,))
    assert (await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/approve", headers=other)).status_code == 404
    r = await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/approve", headers=APPROVER)
    assert r.json()["status"] == "approved" and r.json()["lines"][0]["status"] == "approved"
    pr2 = await ask(client, para)
    r = await client.post(f"{PREFIX}/purchase-requests/{pr2['id']}/reject", json={}, headers=APPROVER)
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/purchase-requests/{pr2['id']}/reject", json={"reason": "Enough in stock"},
                          headers=APPROVER)  # fmt: skip
    assert r.json()["status"] == "rejected" and r.json()["decision_reason"] == "Enough in stock"
    again = await client.post(f"{PREFIX}/purchase-requests/{pr2['id']}/approve", headers=APPROVER)
    assert again.status_code == 409 and again.json()["code"] == "REQUEST_STATE"


async def test_requests_of_two_branches_become_one_po_group(client) -> None:
    supplier = await create_supplier(client)
    para, ors = await add_product("PARA500"), await add_product("ORS", base="sachet", packs=(("box", 20),))
    a = await ask(client, para, 200)
    b = await ask(client, para, 100)  # same branch, same medicine: one PO line
    c = await ask(client, ors, 40, ASKER2, PP2)
    for pr in (a, b, c):
        await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/approve", headers=OWNER)
    lines = [{"request_line_id": a["lines"][0]["id"], "pack_unit_id": para["box"], "qty": 2, "unit_cost": "4.00"},
             {"request_line_id": b["lines"][0]["id"], "pack_unit_id": para["box"], "qty": 1, "unit_cost": "4.00"},
             {"request_line_id": c["lines"][0]["id"], "pack_unit_id": ors["box"], "qty": 2, "unit_cost": "2.50"}]  # fmt: skip
    r = await client.post(f"{PREFIX}/purchase-requests/to-purchase-orders", headers=OWNER,
                          json={"supplier_id": supplier["id"], "lines": lines})  # fmt: skip
    assert r.status_code == 201, r.text
    group = r.json()
    assert group["number"] == "PP1-PG-2026-000001"
    pos = {po["branch_id"]: po for po in group["purchase_orders"]}
    assert set(pos) == {str(PP1), str(PP2)} and all(po["status"] == "draft" for po in pos.values())
    assert [(x["qty"], x["qty_base"]) for x in pos[str(PP1)]["lines"]] == [(3, 300)]
    assert all(po["group_id"] == group["id"] for po in pos.values())
    created = [p for e, p in await outbox() if e == "purchase_order.created"]
    assert {p["group"]["number"] for p in created} == {"PP1-PG-2026-000001"}
    a = (await client.get(f"{PREFIX}/purchase-requests/{a['id']}", headers=ASKER)).json()
    assert a["progress"] == "ordered" and a["lines"][0]["po_number"] == pos[str(PP1)]["number"]
    # a line already ordered cannot be ordered again
    r = await client.post(f"{PREFIX}/purchase-requests/to-purchase-orders", headers=OWNER,
                          json={"supplier_id": supplier["id"], "lines": lines[:1]})  # fmt: skip
    assert r.status_code == 409
    # receiving 2 of the 3 boxes (200 of 300) fills the requests oldest first: a fulfilled, b nothing yet
    po = pos[str(PP1)]
    await client.post(f"{PREFIX}/purchase-orders/{po['id']}/send", headers=OWNER)
    r = await receive(client, po, [{"po_line_id": po["lines"][0]["id"], "qty": 2,
                                    "lot_no": "L1", "expiry_date": "2028-01-31"}])  # fmt: skip
    assert r.status_code == 201, r.text
    a = (await client.get(f"{PREFIX}/purchase-requests/{a['id']}", headers=ASKER)).json()
    b = (await client.get(f"{PREFIX}/purchase-requests/{b['id']}", headers=ASKER)).json()
    assert (a["lines"][0]["fulfilled_base"], a["progress"]) == (200, "fulfilled")
    assert (b["lines"][0]["fulfilled_base"], b["progress"]) == (0, "ordered")


async def test_cancelled_po_puts_lines_back_to_approved(client) -> None:
    supplier = await create_supplier(client)
    para = await add_product("PARA500")
    pr = await ask(client, para)
    await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/approve", headers=OWNER)
    group = (await client.post(f"{PREFIX}/purchase-requests/to-purchase-orders", headers=OWNER, json={
        "supplier_id": supplier["id"], "lines": [{"request_line_id": pr["lines"][0]["id"], "pack_unit_id": para["box"],
                                                  "qty": 2, "unit_cost": "4.00"}]})).json()  # fmt: skip
    po = group["purchase_orders"][0]
    await client.post(f"{PREFIX}/purchase-orders/{po['id']}/cancel", json={"reason": "wrong supplier"}, headers=OWNER)
    pr = (await client.get(f"{PREFIX}/purchase-requests/{pr['id']}", headers=ASKER)).json()
    assert pr["lines"][0]["status"] == "approved" and pr["lines"][0]["po_number"] is None


async def test_filled_by_a_transfer_follows_its_progress_once(client, inventory) -> None:
    para = await add_product("PARA500")
    await inv_event("medicine.created", {
        "medicine_id": para["id"], "version": 1, "sku": "PARA500", "brand_name": "Para", "generic_name": "P",
        "base_unit": "tablet", "is_rx_only": False, "controlled_schedule": None, "is_active": True, "pack_units": []})  # fmt: skip
    await inv_event("goods.received", {
        "receipt_id": str(uuid4()), "number": "PP2-GRN-2026-000001", "po_id": str(uuid4()), "po_number": "x",
        "branch_id": str(PP2), "supplier_id": str(uuid4()), "received_at": "2026-10-20T03:00:00+00:00",
        "received_by": None, "lines": [{"receipt_line_id": str(uuid4()), "medicine_id": para["id"],
                                        "pack_unit_id": para["box"], "qty_base": 500, "lot_no": "SPARE",
                                        "expiry_date": "2027-02-28", "cost_per_base": "0.0400"}]})  # fmt: skip
    pr = await ask(client, para, 120)
    await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/approve", headers=APPROVER)
    body = {"source_branch_id": str(PP2), "line_ids": [pr["lines"][0]["id"]]}
    r = await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/fill-by-transfer", json=body, headers=APPROVER)
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert line["status"] == "transferring" and line["transfer_number"].startswith("PP2-TR-")
    # the source branch picks, dispatches; the requesting branch receives 100 of 120
    src = user("branch_manager", "transfers.dispatch,transfers.receive", (PP2,))
    dst = user("branch_manager", "transfers.receive", (PP1,))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=inventory_main.app), base_url="http://i") as inv:
        tid = line["transfer_id"]
        t = (await inv.get(f"{INV}/transfers/{tid}", headers=src)).json()
        assert t["status"] == "approved"
        await inv.post(f"{INV}/transfers/{tid}/pick", json={}, headers=src)
        t = (await inv.post(f"{INV}/transfers/{tid}/dispatch", json={}, headers={**src, "Idempotency-Key": "d-000001"})).json()
        await relay_transfers()
        await relay_transfers()  # the same events again: nothing changes twice
        await inv.post(f"{INV}/transfers/{tid}/receive", headers={**dst, "Idempotency-Key": "r-000001"},
                       json={"lines": [{"pick_id": t["picks"][0]["id"], "qty_received": 100}]})  # fmt: skip
    await relay_transfers()
    await relay_transfers()
    pr = (await client.get(f"{PREFIX}/purchase-requests/{pr['id']}", headers=ASKER)).json()
    # 20 short is still an open difference on the transfer: not fulfilled yet
    assert (pr["lines"][0]["status"], pr["lines"][0]["fulfilled_base"], pr["progress"]) == (
        "transferring", 100, "partly_fulfilled")  # fmt: skip
    # the same fill again: one transfer only (once per source_ref)
    again = await client.post(f"{PREFIX}/purchase-requests/{pr['id']}/fill-by-transfer", json=body, headers=APPROVER)
    assert again.status_code == 409


async def test_reorder_list_creates_a_request_once(client) -> None:
    para = await add_product("PARA500")
    body = {"branch_id": str(PP1), "source_ref": "reorder:abc", "note": "Re-order list",
            "lines": [{"medicine_id": para["id"], "qty_base": 300, "reason": "Below reorder point"}]}  # fmt: skip
    headers = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "inventory"}
    first = await client.post("/internal/v1/purchase-requests", json=body, headers=headers)
    second = await client.post("/internal/v1/purchase-requests", json=body, headers=headers)
    assert first.status_code == 200 and first.json() == second.json()
    assert (await client.get(f"{PREFIX}/purchase-requests", headers=ASKER)).json()[0]["source_ref"] == "reorder:abc"
