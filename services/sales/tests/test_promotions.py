"""Promotions at the till, manual discount caps with PIN approval, below cost."""

from uuid import uuid4

from sqlalchemy import select

from sales_service.db import db
from sales_service.models import PromotionUse

from .conftest import (
    AUTH,
    CASHIER,
    PP1,
    add_product,
    line,
    pay,
    receive,
    sales_event,
    sell,
    set_rate,
    user,
)

PHARMACIST = user("pharmacist", "pos.sell,sales.view", pharmacist=True)
MANAGER = user("branch_manager", "pos.sell,sales.view,sales.discount,sales.exchange_rate")
OWNER = user("owner", "*", ())


async def promotion(type_: str, code: str = "PROMO", version: int = 1, **rule) -> str:  # noqa: ANN003
    promotion_id = rule.pop("promotion_id", str(uuid4()))
    await sales_event("promotion.created", {
        "promotion_id": promotion_id, "version": version, "code": code, "name": code, "type": type_,
        "value": None, "buy_qty": None, "get_qty": None, "tiers": [], "bundle_items": [], "medicine_ids": [],
        "category_ids": [], "brand_ids": [], "starts_at": None, "ends_at": None, "days_of_week": [],
        "branch_ids": [], "customer_group_ids": [], "max_uses_total": None, "max_uses_per_customer": None,
        "stackable": False, "include_rx": False, "is_active": True, **rule})  # fmt: skip
    return promotion_id


async def stocked(sku: str = "PARA500", **kw) -> dict:  # noqa: ANN003
    p = await add_product(sku, **kw)
    await receive(p, [("A", "2028-01-31", 500)])  # cost 0.04 per tablet
    return p


async def test_buy_two_get_one_on_the_invoice_and_used_once(client) -> None:
    para = await stocked()
    await set_rate(client)
    b2g1 = await promotion("buy_x_get_y", "B2G1", buy_qty=2, get_qty=1, medicine_ids=[para["id"]],
                           max_uses_total=1)  # fmt: skip
    r = await sell(client, [line(para, "tablet", 3)], [pay("0.20")])
    assert r.status_code == 201, r.text
    inv = r.json()
    ln = inv["lines"][0]
    assert (ln["line_total"], ln["promo_discount"], ln["net"], ln["promotion_ids"]) == ("0.30", "0.10", "0.20", [b2g1])
    assert (inv["subtotal"], inv["discount"], inv["total"]) == ("0.30", "0.10", "0.20")
    async with db.sessionmaker() as s:
        assert (await s.execute(select(PromotionUse.status))).scalars().all() == ["used"]
    # max 1 use in total: the next sale pays the full price
    r = await sell(client, [line(para, "tablet", 3)], [pay("0.30")])
    assert r.json()["lines"][0]["promo_discount"] == "0.00"


async def test_window_branch_group_and_rx_exclusion(client, customers_client) -> None:
    para = await stocked()
    await set_rate(client)
    amox = await stocked("AMOX500", rx=True)
    await promotion("percent_off", "LATER", value="50", medicine_ids=[para["id"]], starts_at="2030-01-01T00:00:00+07:00")
    await promotion("percent_off", "ELSEWHERE", value="50", medicine_ids=[para["id"]], branch_ids=[str(uuid4())])
    group = str(uuid4())
    await promotion("group_price", "VIP", value="0.05", medicine_ids=[para["id"]], customer_group_ids=[group])
    await promotion("percent_off", "AMOX", value="50", medicine_ids=[amox["id"]])
    r = await sell(client, [line(para, "strip", 1)], [pay("0.90")])
    assert r.json()["lines"][0]["promo_discount"] == "0.00"  # outside window, other branch, no group
    customer = str(uuid4())
    await sales_event("customer.created", {"customer_id": customer, "phone": "012000999", "name": "VIP",
                                           "group_id": group, "credit_limit": "0", "is_active": True})  # fmt: skip
    r = await sell(client, [line(para, "strip", 1)], [pay("0.50")], customer_id=customer)
    assert r.json()["lines"][0]["promo_discount"] == "0.40"  # 10 tablets at 0.05 instead of 0.10
    from .test_dispensing import RX_PERMS, prescribe

    rx = await prescribe(amox, qty=10)
    pharmacist = user("pharmacist", RX_PERMS, pharmacist=True)
    r = await sell(client, [line(amox, "strip", 1, rx_item_id=rx["item"])], [pay("0.90")], pharmacist)
    assert r.status_code == 201 and r.json()["lines"][0]["promo_discount"] == "0.00"  # Rx-only left out


async def test_stackable_vs_exclusive_on_a_sale(client) -> None:
    para = await stocked()
    await set_rate(client)
    await promotion("percent_off", "TEN", value="10", medicine_ids=[para["id"]])
    await promotion("percent_off", "FIVE", value="5", medicine_ids=[para["id"]], stackable=True)
    await promotion("percent_off", "SIX", value="6", medicine_ids=[para["id"]], stackable=True)
    r = await sell(client, [line(para, "box", 1)], [pay("8.00")])  # 8.00: 10 % = 0.80; 5 % + 6 % = 0.40 + 0.46
    assert r.status_code == 201, r.text
    ln = r.json()["lines"][0]
    assert ln["promo_discount"] == "0.86" and len(ln["promotion_ids"]) == 2


async def test_older_promotion_events_are_ignored(client) -> None:
    para = await stocked()
    await set_rate(client)
    pid = await promotion("percent_off", "P", version=2, value="10", medicine_ids=[para["id"]])
    await promotion("percent_off", "P", version=1, promotion_id=pid, value="90", medicine_ids=[para["id"]])
    await promotion("percent_off", "P", version=2, promotion_id=pid, value="90", medicine_ids=[para["id"]])  # same version
    r = await sell(client, [line(para, "strip", 1)], [pay("0.90")])
    assert r.json()["lines"][0]["promo_discount"] == "0.09"


async def test_below_cost_is_blocked_and_the_stock_released(client) -> None:
    para = await stocked()  # cost 0.04 per tablet
    await promotion("amount_off", "CHEAP", value="0.08", medicine_ids=[para["id"]])  # 0.10 → 0.02 a tablet
    r = await sell(client, [line(para, "tablet", 5)], [pay("0.10")])
    assert r.status_code == 422 and r.json()["code"] == "BELOW_COST"
    from .conftest import inventory_stock

    assert await inventory_stock(para) == {"A": (500, 0, 0)}
    r = await sell(client, [line(para, "tablet", 5)], [pay("0.10")], OWNER)  # sales.below_cost
    assert r.status_code == 201


async def test_manual_discount_cap_and_approval(client) -> None:
    para = await stocked()
    await set_rate(client)
    ok = await sell(client, [line(para, "box", 1, discount_pct="5")], [pay("7.60")])
    assert ok.status_code == 201 and ok.json()["lines"][0]["manual_discount"] == "0.40"
    over = [line(para, "box", 1, discount_pct="15")]
    r = await sell(client, over, [pay("6.80")])
    assert r.status_code == 403 and r.json()["code"] == "DISCOUNT_APPROVAL_REQUIRED"
    assert r.json()["details"]["approver_roles"] == ["branch_manager", "owner"]
    seller = CASHIER["X-User-Id"]
    pharmacist_ok = AUTH.issue(str(uuid4()), "sales.discount", "witness", branches=(PP1,), permissions=("x",))
    r = await sell(client, over, [pay("6.80")], discount_approval_token=pharmacist_ok)
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"
    manager_id = str(uuid4())
    token = AUTH.issue(manager_id, "sales.discount", "witness", branches=(PP1,), permissions=("sales.discount",),
                       role="branch_manager")  # fmt: skip
    r = await sell(client, over, [pay("6.80")], discount_approval_token=token)
    assert r.status_code == 201, r.text
    assert r.json()["lines"][0]["manual_discount_by"] == manager_id
    # the seller cannot approve their own discount
    own = AUTH.issue(seller, "sales.discount", "witness", branches=(PP1,), permissions=("sales.discount",),
                     role="branch_manager")  # fmt: skip
    r = await sell(client, over, [pay("6.80")], discount_approval_token=own)
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"
    # a manager above their own 20 % cap: only the owner
    big = [line(para, "box", 1, discount_pct="30")]
    r = await sell(client, big, [pay("5.60")], MANAGER)
    assert r.status_code == 403 and r.json()["details"]["approver_roles"] == ["owner"]
    other_manager = AUTH.issue(str(uuid4()), "sales.discount", "witness", branches=(PP1,),
                               permissions=("sales.discount",), role="branch_manager")  # fmt: skip
    r = await sell(client, big, [pay("5.60")], MANAGER, discount_approval_token=other_manager)
    assert r.status_code == 422
    owner = AUTH.issue(str(uuid4()), "sales.discount", "witness", branches=(), permissions=("*",), role="owner")
    r = await sell(client, big, [pay("5.60")], MANAGER, discount_approval_token=owner)
    assert r.status_code == 201, r.text
