"""The promotion engine (pure functions): each type, Rx exclusion, stacking vs
exclusive (best deal for the customer)."""

from decimal import Decimal as D
from uuid import uuid4

from sales_service.services.pricing import PriceLine, Promo, best_deal

PARA, ORS, AMOX = uuid4(), uuid4(), uuid4()
PAIN, BRAND = uuid4(), uuid4()


def line(n: int, medicine=PARA, qty: int = 1, qty_base: int = 10, value: str = "1.00", rx: bool = False,  # noqa: ANN001
         category=PAIN, brand=None) -> PriceLine:  # noqa: ANN001  # fmt: skip
    return PriceLine(n, medicine, category, brand, rx, qty, qty_base, D(value))


def promo(type_: str, code: str = "P", stackable: bool = False, **kw) -> Promo:  # noqa: ANN003
    kw.setdefault("medicine_ids", frozenset({PARA}))
    return Promo(id=uuid4(), code=code, type=type_, stackable=stackable, **kw)


def test_percent_and_amount_off() -> None:
    lines = [line(1, value="10.00", qty=2)]
    assert best_deal([promo("percent_off", value=D("15"))], lines).discounts == {1: D("1.50")}
    assert best_deal([promo("amount_off", value=D("0.75"))], lines).discounts == {1: D("1.50")}  # 0.75 × 2
    assert best_deal([promo("amount_off", value=D("9"))], lines).discounts == {1: D("10.00")}  # never below 0


def test_targets_by_category_and_brand() -> None:
    p = Promo(id=uuid4(), code="CAT", type="percent_off", value=D("10"), category_ids=frozenset({PAIN}))
    q = Promo(id=uuid4(), code="BR", type="percent_off", value=D("20"), brand_ids=frozenset({BRAND}))
    lines = [line(1, ORS, value="5.00"), line(2, AMOX, value="5.00", category=None, brand=BRAND)]
    assert best_deal([p], lines).discounts == {1: D("0.50")}
    assert best_deal([q], lines).discounts == {2: D("1.00")}


def test_buy_two_get_one() -> None:
    # 9 tablets at 0.10: 3 free; 10 tablets: still 3 free
    p = promo("buy_x_get_y", buy_qty=2, get_qty=1)
    assert best_deal([p], [line(1, qty=9, qty_base=9, value="0.90")]).discounts == {1: D("0.30")}
    assert best_deal([p], [line(1, qty=10, qty_base=10, value="1.00")]).total == D("0.30")
    # the same medicine on two lines counts together
    split = [line(1, qty=2, qty_base=2, value="0.20"), line(2, qty=1, qty_base=1, value="0.10")]
    assert best_deal([p], split).total == D("0.10")


def test_bundle_price() -> None:
    p = promo("bundle_price", value=D("1.50"), bundle_items=((PARA, 10), (ORS, 2)), medicine_ids=frozenset())
    lines = [line(1, PARA, qty_base=20, value="2.00"), line(2, ORS, qty_base=3, value="0.60")]
    # 2 bundles possible by PARA, only 1 by ORS: one bundle worth 1.00 + 0.40 = 1.40 < 1.50 → no saving
    assert best_deal([p], lines).total == D("0")
    cheaper = promo("bundle_price", value=D("1.00"), bundle_items=((PARA, 10), (ORS, 2)), medicine_ids=frozenset())
    r = best_deal([cheaper], lines)
    assert r.total == D("0.40") and set(r.discounts) == {1, 2}


def test_quantity_tiers() -> None:
    p = promo("qty_tiers", tiers=((50, D("5")), (100, D("10"))))
    assert best_deal([p], [line(1, qty_base=40, value="4.00")]).total == D("0")
    assert best_deal([p], [line(1, qty_base=60, value="6.00")]).total == D("0.30")
    assert best_deal([p], [line(1, qty_base=120, value="12.00")]).total == D("1.20")


def test_group_price() -> None:
    p = promo("group_price", value=D("0.08"))  # 0.08 per base unit instead of 0.10
    assert best_deal([p], [line(1, qty_base=10, value="1.00")]).discounts == {1: D("0.20")}


def test_rx_lines_left_out_unless_included() -> None:
    rx = [line(1, AMOX, value="10.00", rx=True)]
    p = promo("percent_off", value=D("10"), medicine_ids=frozenset({AMOX}))
    assert best_deal([p], rx).total == D("0")
    q = Promo(id=uuid4(), code="RX", type="percent_off", value=D("10"), medicine_ids=frozenset({AMOX}),
              include_rx=True)  # fmt: skip
    assert best_deal([q], rx).total == D("1.00")


def test_stackable_together_vs_exclusive_best_deal_wins() -> None:
    lines = [line(1, value="10.00")]
    ten = promo("percent_off", "A", value=D("10"))  # exclusive: 1.00
    five = promo("percent_off", "B", stackable=True, value=D("5"))
    six = promo("percent_off", "C", stackable=True, value=D("6"))  # 5 % then 6 % of the rest: 0.50 + 0.57
    r = best_deal([ten, five, six], lines)
    assert r.total == D("1.07") and r.promotions[1] == [five.id, six.id]
    twelve = promo("percent_off", "D", value=D("12"))
    r = best_deal([ten, five, six, twelve], lines)
    assert r.total == D("1.20") and r.promotions[1] == [twelve.id]
    # a tie keeps the exclusive one
    tie = promo("percent_off", "E", value=D("10.7"))
    assert best_deal([tie, five, six], lines).promotions[1] == [tie.id]
