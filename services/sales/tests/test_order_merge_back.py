"""A sale from an order that fails part-way gives the held stock back to the order
(while it still holds stock), instead of releasing it."""

from datetime import timedelta
from uuid import uuid4

from pharmacy_shared import clock
from sales_service.services import sale_saga

from .conftest import (
    OWNER,
    PP1,
    PREFIX,
    SUPPLIER,
    add_product,
    inventory_event,
    inventory_stock,
    make_customer,
    user,
)  # fmt: skip

SELLER = user("cashier", "pos.sell,sales.view,sales.orders")


async def expensive_stock(product: dict) -> None:
    """Cost 0.20 a tablet: selling at 0.08 a tablet (8.00 a box) is below cost."""
    await inventory_event("goods.received", {
        "receipt_id": str(uuid4()), "number": "PP1-GRN-2026-000009", "po_id": str(uuid4()),
        "po_number": "PP1-PO-2026-000009", "branch_id": str(PP1), "supplier_id": str(SUPPLIER),
        "received_at": "2026-10-01T03:00:00+00:00", "received_by": None,
        "lines": [{"receipt_line_id": str(uuid4()), "medicine_id": product["id"], "pack_unit_id": product["box"],
                   "qty_base": 300, "lot_no": "A", "expiry_date": "2028-01-31", "cost_per_base": "0.2000",
                   "controlled_schedule": None, "is_controlled": False}]})  # fmt: skip


async def ordered(client, customers_client) -> tuple[dict, dict]:  # noqa: ANN001
    para = await add_product("PARA500")
    await expensive_stock(para)
    customer = await make_customer(customers_client)
    o = (await client.post(f"{PREFIX}/sale-orders", headers=SELLER, json={
        "branch_id": str(PP1), "customer_id": customer["id"],
        "lines": [{"medicine_id": para["id"], "pack_unit_id": para["box"], "qty": 2}]})).json()  # fmt: skip
    r = await client.post(f"{PREFIX}/sale-orders/{o['id']}/confirm", json={"reserve": True, "reserve_days": 3},
                          headers={**SELLER, "Idempotency-Key": f"c-{o['id']}"})  # fmt: skip
    assert r.status_code == 200, r.text
    return para, r.json()


async def invoice(client, o: dict, qty: int, who: dict, key: str):  # noqa: ANN001, ANN201
    return await client.post(f"{PREFIX}/sale-orders/{o['id']}/invoice", headers={**who, "Idempotency-Key": key},
                             json={"lines": [{"order_line_id": o["lines"][0]["id"], "qty": qty}],
                                   "payments": [{"method": "cash", "amount": str(8 * qty)}]})  # fmt: skip


async def test_failed_order_sale_gives_the_stock_back_to_the_order(client, customers_client) -> None:
    para, o = await ordered(client, customers_client)
    assert await inventory_stock(para) == {"A": (300, 200, 0)}
    r = await invoice(client, o, 1, SELLER, "merge-back-0001")
    assert r.status_code == 422 and r.json()["code"] == "BELOW_COST"
    assert await inventory_stock(para) == {"A": (300, 200, 0)}  # both boxes still held for the order
    r = await invoice(client, o, 2, OWNER, "merge-back-0002")  # sales.below_cost: the whole order, from its reservation
    assert r.status_code == 201, r.text
    assert await inventory_stock(para) == {"A": (100, 0, 0)}


async def test_after_reserve_until_the_failed_part_is_released(client, customers_client, monkeypatch) -> None:
    para, o = await ordered(client, customers_client)
    later = clock.now() + timedelta(days=4)
    below_cost = sale_saga._below_cost

    def expire_then_check(*args):  # noqa: ANN002, ANN202
        monkeypatch.setattr(clock, "now", lambda: later)  # the order's hold ran out during the sale
        return below_cost(*args)

    monkeypatch.setattr(sale_saga, "_below_cost", expire_then_check)
    r = await invoice(client, o, 1, SELLER, "merge-back-0003")
    assert r.status_code == 422 and r.json()["code"] == "BELOW_COST"
    assert await inventory_stock(para) == {"A": (300, 100, 0)}  # the failed box released; the order's other box
