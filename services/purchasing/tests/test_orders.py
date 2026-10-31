from uuid import uuid4

from .conftest import (
    CASHIER,
    MANAGER,
    OTHER_MANAGER,
    OWNER,
    PP1,
    PP2,
    PREFIX,
    add_product,
    audits,
    create_po,
    create_supplier,
    event,
    outbox,
)


async def test_po_is_numbered_per_branch_and_year_with_lines_in_base_units(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 10, "4.25"), (para, "strip", 5, "0.45")])
    assert po["number"] == "PP1-PO-2026-000001" and po["status"] == "draft"
    assert [(line["qty"], line["qty_base"]) for line in po["lines"]] == [(10, 1000), (5, 50)]
    assert po["total"] == "44.75"
    assert (await create_po(client, s, [(para, "box", 1, "4")]))["number"] == "PP1-PO-2026-000002"
    assert (await create_po(client, s, [(para, "box", 1, "4")], branch=PP2))["number"] == "PP2-PO-2026-000001"


async def test_po_event_carries_the_whole_order_for_the_pdf(client) -> None:
    s = await create_supplier(client, address="St 1, Phnom Penh")
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 10, "4.25")])
    payload = next(p for t, p in await outbox() if t == "purchase_order.created")
    assert payload["number"] == po["number"] and payload["version"] == 1
    assert payload["branch"] == {"id": str(PP1), "code": "PP1", "name_en": "Phnom Penh 1", "name_km": "សាខា១"}
    assert payload["supplier"]["address"] == "St 1, Phnom Penh"
    line = payload["lines"][0]
    assert (line["sku"], line["pack_unit"], line["qty"], line["unit_cost"], line["line_total"]) == (
        "PARA500", "box", 10, "4.2500", "42.50",
    )  # fmt: skip
    assert line["name_km"] == "ថ្នាំ" and payload["total"] == "42.50"
    assert (await audits())[-1]["action"] == "purchase_order.created"


async def test_po_lines_must_be_known_active_products_listed_once(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    old = await add_product("OLD1", active=False)
    body = {"branch_id": str(PP1), "supplier_id": s["id"]}
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OWNER, json={**body, "lines": [
        {"medicine_id": str(uuid4()), "pack_unit_id": str(uuid4()), "qty": 1, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_MEDICINE"
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OWNER, json={**body, "lines": [
        {"medicine_id": old["id"], "pack_unit_id": old["box"], "qty": 1, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 422 and "deactivated" in r.json()["message"]
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OWNER, json={**body, "lines": [
        {"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 1, "unit_cost": "1"},
        {"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 2, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OWNER, json={**body, "lines": [
        {"medicine_id": para["id"], "pack_unit_id": old["box"], "qty": 1, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 422  # pack unit of another medicine


async def test_inactive_supplier_or_unknown_branch_is_refused(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    await client.post(f"{PREFIX}/suppliers/{s['id']}/deactivate", json={"reason": "x"}, headers=OWNER)
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OWNER, json={
        "branch_id": str(PP1), "supplier_id": s["id"],
        "lines": [{"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 1, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_SUPPLIER"
    s2 = await create_supplier(client, code="S2")
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OWNER, json={
        "branch_id": str(uuid4()), "supplier_id": s2["id"],
        "lines": [{"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 1, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_BRANCH"


async def test_staff_work_only_in_their_branches(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 1, "4")])  # PP1
    assert (
        await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=OTHER_MANAGER)
    ).status_code == 404
    assert (await client.get(f"{PREFIX}/purchase-orders", headers=OTHER_MANAGER)).json()["total"] == 0
    r = await client.post(f"{PREFIX}/purchase-orders/{po['id']}/send", headers=OTHER_MANAGER)
    assert r.status_code == 404
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OTHER_MANAGER, json={
        "branch_id": str(PP1), "supplier_id": s["id"],
        "lines": [{"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 1, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 403 and r.json()["code"] == "BRANCH_FORBIDDEN"
    assert (await client.get(f"{PREFIX}/purchase-orders", headers=MANAGER)).json()["total"] == 1


async def test_edit_only_in_draft_then_send_locks_it(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 10, "4")])
    r = await client.patch(f"{PREFIX}/purchase-orders/{po['id']}", headers=OWNER, json={
        "note": "urgent", "lines": [{"medicine_id": para["id"], "pack_unit_id": para["strip"], "qty": 3,
                                     "unit_cost": "0.5"}]})  # fmt: skip
    assert r.status_code == 200 and r.json()["lines"][0]["qty_base"] == 30 and r.json()["version"] == 2
    r = await client.post(f"{PREFIX}/purchase-orders/{po['id']}/send", headers=OWNER)
    assert r.json()["status"] == "sent" and r.json()["sent_at"]
    r = await client.patch(f"{PREFIX}/purchase-orders/{po['id']}", json={"note": "x"}, headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "PO_STATE"
    assert (await client.post(f"{PREFIX}/purchase-orders/{po['id']}/send", headers=OWNER)).status_code == 409
    actions = [a["action"] for a in await audits()]
    assert actions[-2:] == ["purchase_order.updated", "purchase_order.sent"]


async def test_cancel_needs_a_reason_and_nothing_received(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 10, "4")], send=True)
    r = await client.post(f"{PREFIX}/purchase-orders/{po['id']}/cancel", json={}, headers=OWNER)
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/purchase-orders/{po['id']}/cancel", json={"reason": "wrong supplier"},
                          headers=OWNER)  # fmt: skip
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "wrong supplier"
    assert (await audits())[-1]["after"] == {"status": "cancelled", "reason": "wrong supplier"}
    assert (await client.delete(f"{PREFIX}/purchase-orders/{po['id']}", headers=OWNER)).status_code == 405


async def test_cashier_cannot_create_pos_and_sees_no_prices(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 10, "4")])
    r = await client.post(f"{PREFIX}/purchase-orders", headers=CASHIER, json={
        "branch_id": str(PP1), "supplier_id": s["id"],
        "lines": [{"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 1, "unit_cost": "1"}]})  # fmt: skip
    assert r.status_code == 403
    seen = (await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=CASHIER)).json()
    assert (
        "total" not in seen and "unit_cost" not in seen["lines"][0] and "line_total" not in seen["lines"][0]
    )
    assert seen["lines"][0]["qty"] == 10
    assert (await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=MANAGER)).json()[
        "total"
    ] == "40.00"


async def test_a_hamper_cannot_be_ordered(client) -> None:
    supplier = await create_supplier(client)
    para = await add_product("PARA500")
    hamper_id, pack = str(uuid4()), str(uuid4())
    await event("medicine.created", {
        "medicine_id": hamper_id, "version": 1, "sku": "KIT-FLU", "brand_name": "Flu kit", "generic_name": "Hamper",
        "base_unit": "hamper", "is_rx_only": False, "controlled_schedule": None, "is_active": True, "kind": "hamper",
        "components": [{"medicine_id": para["id"], "qty_base": 10}],
        "pack_units": [{"id": pack, "name": "hamper", "qty_in_base": 1, "barcode": None, "sell_price": "5.00",
                        "is_base": True, "is_active": True}]})  # fmt: skip
    r = await client.post(f"{PREFIX}/purchase-orders", headers=OWNER, json={
        "branch_id": str(PP1), "supplier_id": supplier["id"],
        "lines": [{"medicine_id": hamper_id, "pack_unit_id": pack, "qty": 1, "unit_cost": "3.00"}]})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "HAMPER_NOT_STOCKED"
