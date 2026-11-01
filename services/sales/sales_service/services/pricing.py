"""Promotion pricing: pure functions (no database), tested in tests/test_pricing.py.

A cart line has its list value (sell price × qty). Each applicable promotion
gives line discounts:

- percent_off   value % of the line
- amount_off    value USD per unit sold (the line's pack unit), at most the line
- buy_x_get_y   per medicine: of every buy_qty + get_qty base units, get_qty are
                free (valued at that medicine's base unit price in the cart)
- bundle_price  each complete bundle (bundle_items, base units) costs value USD
- qty_tiers     per medicine: the highest tier reached by its base quantity
- group_price   value USD per base unit (eligibility checked by the caller)

Rx-only and controlled lines are left out unless the promotion has include_rx.

Best deal for the customer: the options are each exclusive promotion alone, and
all stackable promotions together (applied one after the other, in code order,
on what is left of each line). The option with the largest total discount wins;
on a tie an exclusive promotion is kept. No line goes below zero.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceLine:
    line_no: int
    medicine_id: UUID
    category_id: UUID | None
    brand_id: UUID | None
    is_rx: bool  # Rx-only or controlled
    qty: int  # in the line's pack unit
    qty_base: int
    value: Decimal  # sell price × qty, USD


@dataclass(frozen=True)
class Promo:
    id: UUID
    code: str
    type: str
    value: Decimal | None = None
    buy_qty: int | None = None
    get_qty: int | None = None
    tiers: tuple[tuple[int, Decimal], ...] = ()
    bundle_items: tuple[tuple[UUID, int], ...] = ()
    medicine_ids: frozenset[UUID] = frozenset()
    category_ids: frozenset[UUID] = frozenset()
    brand_ids: frozenset[UUID] = frozenset()
    stackable: bool = False
    include_rx: bool = False

    def targets(self, line: PriceLine) -> bool:
        if line.is_rx and not self.include_rx:
            return False
        if self.type == "bundle_price":
            return line.medicine_id in {m for m, _ in self.bundle_items}
        return (line.medicine_id in self.medicine_ids or (line.category_id in self.category_ids)
                or (line.brand_id in self.brand_ids))  # fmt: skip


@dataclass
class Result:
    discounts: dict[int, Decimal] = field(default_factory=dict)  # line_no → USD
    promotions: dict[int, list[UUID]] = field(default_factory=dict)  # line_no → promotions used on it
    amounts: dict[tuple[int, UUID], Decimal] = field(default_factory=dict)  # (line_no, promotion) → USD

    @property
    def total(self) -> Decimal:
        return sum(self.discounts.values(), ZERO)

    @property
    def used(self) -> set[UUID]:
        return {p for ids in self.promotions.values() for p in ids}


def _spread(
    amount: Decimal, lines: list[PriceLine], weights: list[Decimal], left: dict[int, Decimal]
) -> dict[int, Decimal]:
    """Share an amount over lines by weight, in cents, none beyond what is left."""
    total = sum(weights, ZERO)
    out: dict[int, Decimal] = {}
    if amount <= 0 or total <= 0:
        return out
    given = ZERO
    for i, (line, w) in enumerate(zip(lines, weights, strict=True)):
        share = amount - given if i == len(lines) - 1 else cents(amount * w / total)
        share = max(min(share, left[line.line_no]), ZERO)
        if share > 0:
            out[line.line_no] = share
            given += share
    return out


def _base_price(lines: list[PriceLine], left: dict[int, Decimal]) -> Decimal:
    qty = sum(x.qty_base for x in lines)
    return sum((left[x.line_no] for x in lines), ZERO) / qty if qty else ZERO


def apply(promo: Promo, lines: list[PriceLine], left: dict[int, Decimal]) -> dict[int, Decimal]:
    """The discounts one promotion gives on what is left of each line."""
    mine = [x for x in lines if promo.targets(x) and left[x.line_no] > 0]
    if not mine:
        return {}
    value = promo.value or ZERO
    t = promo.type
    if t == "percent_off":
        return {x.line_no: min(cents(left[x.line_no] * value / 100), left[x.line_no]) for x in mine}
    if t == "amount_off":
        return {x.line_no: min(cents(value * x.qty), left[x.line_no]) for x in mine}
    if t == "group_price":
        return {x.line_no: max(left[x.line_no] - cents(value * x.qty_base), ZERO) for x in mine}
    by_medicine: dict[UUID, list[PriceLine]] = defaultdict(list)
    for x in mine:
        by_medicine[x.medicine_id].append(x)
    out: dict[int, Decimal] = {}
    if t == "buy_x_get_y":
        step = (promo.buy_qty or 0) + (promo.get_qty or 0)
        for group in by_medicine.values():
            free = sum(x.qty_base for x in group) // step * (promo.get_qty or 0) if step else 0
            amount = cents(free * _base_price(group, left))
            out |= _spread(amount, group, [Decimal(x.qty_base) for x in group], left)
        return out
    if t == "qty_tiers":
        for group in by_medicine.values():
            qty = sum(x.qty_base for x in group)
            reached = [pct for min_qty, pct in promo.tiers if qty >= min_qty]
            if reached:
                pct = max(reached)
                out |= {x.line_no: min(cents(left[x.line_no] * pct / 100), left[x.line_no]) for x in group}
        return out
    if t == "bundle_price":
        need = dict(promo.bundle_items)
        have = {m: sum(x.qty_base for x in g) for m, g in by_medicine.items()}
        bundles = min((have.get(m, 0) // q for m, q in need.items()), default=0)
        if bundles <= 0:
            return {}
        parts = [
            (m, by_medicine[m], bundles * q * _base_price(by_medicine[m], left)) for m, q in need.items()
        ]
        normal = sum((v for _, _, v in parts), ZERO)
        saving = cents(normal - bundles * value)
        if saving <= 0:
            return {}
        involved, weights = [], []
        for _, group, v in parts:
            qty = sum(x.qty_base for x in group)
            for x in group:
                involved.append(x)
                weights.append(v * x.qty_base / qty)
        return _spread(saving, involved, weights, left)
    return {}


def _run(promos: list[Promo], lines: list[PriceLine]) -> Result:
    left = {x.line_no: x.value for x in lines}
    result = Result()
    for promo in promos:
        for line_no, d in apply(promo, lines, left).items():
            if d <= 0:
                continue
            left[line_no] -= d
            result.discounts[line_no] = result.discounts.get(line_no, ZERO) + d
            result.promotions.setdefault(line_no, []).append(promo.id)
            result.amounts[(line_no, promo.id)] = d
    return result


def best_deal(promos: list[Promo], lines: list[PriceLine]) -> Result:
    best = Result()
    for promo in sorted((p for p in promos if not p.stackable), key=lambda p: p.code):
        option = _run([promo], lines)
        if option.total > best.total:
            best = option
    stackable = sorted((p for p in promos if p.stackable), key=lambda p: p.code)
    if stackable:
        option = _run(stackable, lines)
        if option.total > best.total:  # a tie keeps the exclusive one
            best = option
    return best
