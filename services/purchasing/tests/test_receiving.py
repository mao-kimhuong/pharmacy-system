from .conftest import (
    CASHIER,
    MANAGER,
    OWNER,
    PREFIX,
    add_product,
    audits,
    create_po,
    create_supplier,
    idem,
    outbox,
    receive,
)


async def setup(client, controlled: str | None = None) -> tuple[dict, dict, dict]:
    s = await create_supplier(client)
    para = await add_product("PARA500", controlled=controlled)
    po = await create_po(client, s, [(para, "box", 10, "4.25")], send=True)
    return s, para, po


def lot(po: dict, lot_no: str, expiry: str, qty: int, **extra) -> dict:
    return {"po_line_id": po["lines"][0]["id"], "lot_no": lot_no, "expiry_date": expiry, "qty": qty, **extra}


async def test_two_lots_of_one_line_create_a_bill_and_goods_received(client) -> None:
    _, para, po = await setup(client)
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 6), lot(po, "B2", "2028-09-30", 4)],
                      supplier_invoice_no="INV-778")  # fmt: skip
    assert r.status_code == 201, r.text
    receipt = r.json()
    assert receipt["number"] == "PP1-GRN-2026-000001" and receipt["supplier_invoice_no"] == "INV-778"
    assert receipt["total"] == "42.50" and receipt["status"] == "open"
    assert receipt["due_on"] == "2026-11-26"  # 30 days payment terms
    assert [(x["lot_no"], x["qty_base"], x["cost_per_base"]) for x in receipt["lines"]] == [
        ("A1", 600, "0.0425"), ("B2", 400, "0.0425"),
    ]  # fmt: skip
    po_now = (await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=OWNER)).json()
    assert po_now["status"] == "received" and po_now["lines"][0]["qty_received_base"] == 1000

    goods = next(p for t, p in await outbox() if t == "goods.received")
    assert goods["branch_id"] == po["branch_id"] and goods["supplier_id"] == po["supplier"]["id"]
    assert goods["lines"][0] == {
        "receipt_line_id": receipt["lines"][0]["id"], "medicine_id": para["id"], "pack_unit_id": para["box"],
        "qty_base": 600, "lot_no": "A1", "expiry_date": "2028-03-31", "cost_per_base": "0.0425",
        "line_total": "25.50", "controlled_schedule": None, "is_controlled": False,
    }  # fmt: skip
    assert (goods["total"], goods["due_on"]) == ("42.50", "2026-11-26")  # the bill, for payables aging
    assert (await audits())[-1]["action"] == "goods.received"


async def test_partial_receiving_keeps_the_po_open(client) -> None:
    _, _, po = await setup(client)
    await receive(client, po, [lot(po, "A1", "2028-03-31", 3)])
    po_now = (await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=OWNER)).json()
    assert po_now["status"] == "partially_received"
    r = await client.post(f"{PREFIX}/purchase-orders/{po['id']}/cancel", json={"reason": "x"}, headers=OWNER)
    assert r.status_code == 409  # something was received
    await receive(client, po, [lot(po, "A1", "2028-03-31", 7)])
    po_now = (await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=OWNER)).json()
    assert po_now["status"] == "received"


async def test_past_expiry_is_refused(client) -> None:
    _, _, po = await setup(client)
    r = await receive(client, po, [lot(po, "OLD", "2026-10-26", 1)])  # today is 2026-10-27
    assert r.status_code == 409 and r.json()["code"] == "BATCH_EXPIRED"
    assert not [t for t, _ in await outbox() if t == "goods.received"]
    r = await receive(client, po, [lot(po, "TODAY", "2026-10-27", 1)])  # still good today
    assert r.status_code == 201


async def test_short_expiry_is_accepted_but_flagged(client) -> None:
    _, _, po = await setup(client)
    r = await receive(client, po, [lot(po, "SOON", "2027-04-24", 1), lot(po, "OK", "2027-04-25", 1)])
    assert [x["short_expiry"] for x in r.json()["lines"]] == [True, False]  # 179 vs 180 days
    assert (await audits())[-1]["after"]["short_expiry"] == ["lot SOON exp 2027-04-24"]


async def test_receiving_more_than_ordered(client) -> None:
    _, _, po = await setup(client)
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 11)])
    assert r.status_code == 422 and r.json()["code"] == "RECEIVE_EXCEEDS_ORDER"
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 11)], headers=CASHIER, allow_over=True)
    assert r.status_code == 403  # cashier has no purchasing.over_receive
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 11)], headers=MANAGER, allow_over=True)
    assert r.status_code == 201 and r.json()["lines"][0]["over_received"] is True


async def test_draft_po_cannot_be_received(client) -> None:
    s = await create_supplier(client)
    para = await add_product("PARA500")
    po = await create_po(client, s, [(para, "box", 10, "4")])
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 1)])
    assert r.status_code == 409 and r.json()["code"] == "PO_STATE"


async def test_same_idempotency_key_receives_once(client) -> None:
    _, _, po = await setup(client)
    key = idem()
    first = await receive(client, po, [lot(po, "A1", "2028-03-31", 4)], key=key)
    again = await receive(client, po, [lot(po, "A1", "2028-03-31", 4)], key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert [t for t, _ in await outbox()].count("goods.received") == 1
    po_now = (await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=OWNER)).json()
    assert po_now["lines"][0]["qty_received_base"] == 400
    r = await client.post(f"{PREFIX}/purchase-orders/{po['id']}/receive", json={"lines": []}, headers=OWNER)
    assert r.status_code == 400 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_cashier_receives_without_seeing_or_changing_prices(client) -> None:
    _, _, po = await setup(client)
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 1, unit_cost="1.00")], headers=CASHIER)
    assert r.status_code == 403
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 1)], headers=CASHIER)
    assert r.status_code == 201
    body = r.json()
    assert not {"total", "paid", "balance"} & set(body)
    assert not {"unit_cost", "cost_per_base", "line_total"} & set(body["lines"][0])
    assert body["lines"][0]["lot_no"] == "A1"


async def test_controlled_flag_travels_with_the_receipt(client) -> None:
    _, _, po = await setup(client, controlled="IV")
    await receive(client, po, [lot(po, "D1", "2028-03-31", 1)])
    goods = next(p for t, p in await outbox() if t == "goods.received")
    assert goods["lines"][0]["is_controlled"] is True and goods["lines"][0]["controlled_schedule"] == "IV"


async def test_receiving_at_another_cost(client) -> None:
    _, _, po = await setup(client)
    r = await receive(client, po, [lot(po, "A1", "2028-03-31", 2, unit_cost="5.00")], headers=MANAGER)
    assert r.json()["lines"][0]["cost_per_base"] == "0.0500" and r.json()["total"] == "10.00"


async def test_supplier_confirms_a_sent_po_on_telegram_once(client) -> None:
    """T2: /internal/v1/purchase-orders/{id}/supplier-confirm (notification checked the chat is that supplier's)."""
    from uuid import uuid4

    from .conftest import SERVICE_TOKEN

    s = await create_supplier(client)
    para = await add_product("PARA500")
    draft = await create_po(client, s, [(para, "box", 1, "4.25")])
    internal = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "notification"}
    url = f"/internal/v1/purchase-orders/{draft['id']}/supplier-confirm"
    r = await client.post(url, json={"supplier_id": s["id"], "by": "Vuthy"}, headers=internal)
    assert r.status_code == 409  # a draft was never sent
    po = await create_po(client, s, [(para, "box", 1, "4.25")], send=True)
    url = f"/internal/v1/purchase-orders/{po['id']}/supplier-confirm"
    assert (await client.post(url, json={"supplier_id": str(uuid4()), "by": "x"}, headers=internal)).status_code == 404
    assert (await client.post(url, json={"supplier_id": s["id"], "by": "x"})).status_code == 401
    first = (await client.post(url, json={"supplier_id": s["id"], "by": "Vuthy"}, headers=internal)).json()
    again = (await client.post(url, json={"supplier_id": s["id"], "by": "Someone else"}, headers=internal)).json()
    assert first == again and first["supplier_confirmed_by"] == "Vuthy"
    shown = (await client.get(f"{PREFIX}/purchase-orders/{po['id']}", headers=OWNER)).json()
    assert shown["supplier_confirmed_by"] == "Vuthy" and shown["supplier_confirmed_at"]
    assert [a["action"] for a in await audits()].count("purchase_order.supplier_confirmed") == 1
