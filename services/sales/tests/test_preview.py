"""POST /carts/preview: the same checks as POST /invoices (same codes), nothing
written, warnings resolved by their override, KHR as money.py, and the catalog's
promotion preview with a draft promotion (conflicts)."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from sales_service.db import db
from sales_service.services import money

from .conftest import (
    CASHIER,
    MANAGER,
    OWNER,
    PP1,
    PREFIX,
    SERVICE_TOKEN,
    add_product,
    customers_db,
    inventory_db,
    line,
    make_customer,
    pay,
    sell,
    set_rate,
    user,
)  # fmt: skip
from .test_dispensing import PHARMACIST, prescribe, stocked_rx_product
from .test_promotions import promotion, stocked


async def preview(client, lines: list[dict], headers: dict = CASHIER, **extra):  # noqa: ANN001, ANN003, ANN201
    r = await client.post(f"{PREFIX}/carts/preview", json={"branch_id": str(PP1), "lines": lines, **extra},
                          headers=headers)  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def codes(p: dict, severity: str = "hard_stops") -> set[str]:
    return {f["code"] for f in p[severity]} | {f["code"] for x in p["lines"] for f in x[severity]}


async def counts() -> tuple:
    async def n(engine, table: str) -> int:
        async with engine.connect() as conn:
            return (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608 – fixed names

    return (await n(db.engine, "invoices"), await n(db.engine, "outbox"), await n(db.engine, "promotion_uses"),
            await n(inventory_db.engine, "reservations"), await n(customers_db.engine, "ledger_entries"))  # fmt: skip


CASES = ["UNKNOWN_MEDICINE", "RX_REQUIRED", "OUT_OF_STOCK", "BELOW_COST", "CUSTOMER_REQUIRED", "CREDIT_LIMIT_EXCEEDED",
         "EXCHANGE_RATE_MISSING", "PHARMACIST_REQUIRED"]  # fmt: skip


@pytest.mark.parametrize("code", CASES)
async def test_preview_and_posting_give_the_same_code(client, customers_client, code) -> None:
    para = await stocked()
    amox = await add_product("AMOX500", rx=True)
    extra: dict = {}
    who = CASHIER
    lines, payments = [line(para, "strip", 1)], [pay("0.90")]
    if code == "UNKNOWN_MEDICINE":
        lines = [{**line(para, "strip", 1), "pack_unit_id": str(uuid4())}]
    elif code == "RX_REQUIRED":
        lines = [line(amox, "strip", 1)]
    elif code == "OUT_OF_STOCK":
        lines = [line(para, "box", 6)]
        payments = [pay("48.00")]
    elif code == "BELOW_COST":
        await promotion("amount_off", "CHEAP", value="0.08", medicine_ids=[para["id"]])
        lines, payments = [line(para, "tablet", 5)], [pay("0.10")]
    elif code == "CUSTOMER_REQUIRED":
        payments = [pay("0.90", method="credit")]
    elif code == "CREDIT_LIMIT_EXCEEDED":
        customer = await make_customer(customers_client, limit="0.50")
        extra = {"customer_id": customer["id"]}
        payments = [pay("0.90", method="credit")]
    elif code == "EXCHANGE_RATE_MISSING":
        payments = [pay("4000", "KHR")]
    elif code == "PHARMACIST_REQUIRED":
        lines = [line(para, "strip", 1, rx_item_id=str(uuid4()))]
    if code != "EXCHANGE_RATE_MISSING":
        await set_rate(client)
    before = await counts()
    p = await preview(client, lines, who, payments=payments, **extra)
    assert await counts() == before  # the preview wrote nothing anywhere
    assert code in codes(p) and p["can_post"] is False, p
    r = await sell(client, lines, payments, who, **extra)
    assert r.status_code >= 400 and r.json()["code"] == code, r.text


async def test_clean_cart_promotions_batches_khr(client) -> None:
    para = await stocked()
    await set_rate(client, 4100)
    pid = await promotion("percent_off", "TEN", value="10", medicine_ids=[para["id"]])
    p = await preview(client, [line(para, "strip", 3)])
    ln = p["lines"][0]
    assert p["can_post"] and ln["promo_discount"] == "0.27" and ln["net"] == "2.43"
    assert ln["promotions"] == [{"id": pid, "code": "TEN", "name_en": "TEN", "name_km": "", "discount": "0.27"}]
    assert [(b["lot_no"], b["qty_base"]) for b in ln["batches"]] == [("A", 30)] and "cost_per_base" not in ln["batches"][0]
    assert p["total_khr"] == money.round_riel(money.usd("2.43") * 4100) == 10000
    assert p["rounding_khr"] == "37.00"  # 9963 riel exact → 10000 on the receipt
    owner = await preview(client, [line(para, "strip", 3)], OWNER)
    assert owner["lines"][0]["batches"][0]["cost_per_base"] == "0.0400"


async def test_requirements_are_reported_but_never_consumed(client) -> None:
    para = await stocked()
    await set_rate(client)
    p = await preview(client, [line(para, "box", 1, discount_pct="15")])  # cashier cap 5 %
    req = p["requirements"][0]
    assert req["code"] == "DISCOUNT_APPROVAL_REQUIRED" and not req["resolved"] and p["can_post"]
    assert req["message_km"]


async def test_warning_resolved_by_its_override_then_posting_works(client) -> None:
    amox = await stocked_rx_product(classes=("penicillins",), ingredients=("Amoxicillin",))
    await set_rate(client)
    rx = await prescribe(amox, allergies=[{"kind": "class", "value": "penicillins"}])
    p = await preview(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], PHARMACIST)
    warning = p["lines"][0]["warnings"][0]
    assert warning["code"] == "ALLERGY_WARNING" and not warning["resolved"] and p["can_post"] is False
    override = line(amox, "strip", 1, rx_item_id=rx["item"], allergy_override_reason="no reaction before")
    p = await preview(client, [override], PHARMACIST)
    assert p["can_post"] and p["lines"][0]["warnings"][0]["resolved"]
    assert (await sell(client, [override], [pay("0.90")], PHARMACIST)).status_code == 201
    cashier = await preview(client, [override], user("cashier", "pos.sell"))
    assert "PHARMACIST_REQUIRED" in codes(cashier)


async def test_draft_promotion_preview_with_conflicts(client) -> None:
    para = await stocked()
    await promotion("percent_off", "OLD5", value="5", medicine_ids=[para["id"]])
    draft = {"promotion_id": str(uuid4()), "code": "NEW20", "name": "New 20", "type": "percent_off", "value": "20",
             "medicine_ids": [para["id"]], "stackable": False, "include_rx": False, "branch_ids": [],
             "customer_group_ids": []}  # fmt: skip
    body = {"cart": {"branch_id": str(PP1), "lines": [line(para, "strip", 1)]}, "draft_promotion": draft}
    headers = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "catalog"}
    r = await client.post("/internal/v1/carts/preview", json=body, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["lines"][0]["promotions"][0]["code"] == "NEW20" and out["lines"][0]["promo_discount"] == "0.18"
    assert out["conflicts"] == [{"line_no": 1, "promotions": ["NEW20", "OLD5"], "applied": ["NEW20"],
                                 "draft_wins": True}]  # fmt: skip
    assert (await client.post("/internal/v1/carts/preview", json=body)).status_code == 401
    assert MANAGER  # (the public preview needs pos.sell; the internal one the service token)
