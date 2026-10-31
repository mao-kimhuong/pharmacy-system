"""Pricing a cart (the till, suspend / resume, templates, quotes). Rules:

- Price = the pack unit's sell price from the local catalog copy.
- Promotions: promotions.price (best deal). Rx-only and controlled lines are
  left out unless the promotion includes them.
- Manual discount per line, after promotions: `discount_pct` or
  `discount_amount` (USD), never more than what is left of the line.
- Cap per role (branch setting max_discount_pct: cashier 5, pharmacist 10,
  branch_manager 20; the owner has none), as a % of the line after promotions.
  Above it a second person confirms with their PIN on this device (auth
  /pin/witness, action sales.discount): a branch manager or the owner with
  sales.discount, never the seller; above a manager's own cap only the owner.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.pin import consume_witness

from ..models import BranchSettingsCopy, KnownCustomer, ProductPackUnit
from . import money, promotions
from .pricing import PriceLine, cents

DEFAULT_CAPS = {"cashier": 5, "pharmacist": 10, "branch_manager": 20}
ZERO = Decimal("0.00")


@dataclass
class PricedLine:
    line_no: int
    pack: ProductPackUnit
    qty: int
    unit_price: Decimal
    line_total: Decimal
    promo_discount: Decimal = ZERO
    promotion_ids: list[str] = field(default_factory=list)
    manual_discount: Decimal = ZERO

    @property
    def qty_base(self) -> int:
        return self.qty * self.pack.qty_in_base

    @property
    def net(self) -> Decimal:
        return self.line_total - self.promo_discount - self.manual_discount

    def as_dict(self) -> dict[str, Any]:
        p = self.pack.product
        return {"line_no": self.line_no, "medicine_id": str(p.id), "pack_unit_id": str(self.pack.id), "sku": p.sku,
                "name": p.display_name, "pack_unit": self.pack.name, "qty": self.qty,
                "unit_price": str(self.unit_price), "line_total": str(self.line_total),
                "promo_discount": str(self.promo_discount), "promotion_ids": self.promotion_ids,
                "manual_discount": str(self.manual_discount), "net": str(self.net), "is_hamper": p.is_hamper,
                "is_rx_only": p.is_rx_only}  # fmt: skip


async def pack_for(
    session: AsyncSession, medicine_id: UUID, pack_unit_id: UUID, line_no: int
) -> ProductPackUnit:
    pack = (
        await session.execute(select(ProductPackUnit).where(ProductPackUnit.id == pack_unit_id))
    ).scalar_one_or_none()
    if pack is None or pack.product_id != medicine_id:
        raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {line_no}: unknown medicine or pack unit", status_code=422,
                       details={"line": line_no})  # fmt: skip
    if not (pack.is_active and pack.product.is_active):
        raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {line_no}: {pack.product.sku} ({pack.name}) is not sold "
                       "any more", status_code=422, details={"line": line_no})  # fmt: skip
    return pack


def price_line(line_no: int, pack: ProductPackUnit, qty: int) -> PricedLine:
    return PricedLine(line_no, pack, qty, pack.sell_price, money.usd(pack.sell_price * qty))


async def apply_promotions(session: AsyncSession, branch_id: UUID, customer: KnownCustomer | None,
                           lines: list[PricedLine]) -> None:  # fmt: skip
    priceable = [x for x in lines if x.promo_discount == ZERO and not x.promotion_ids]
    result = await promotions.price(session, branch_id, customer, [
        PriceLine(x.line_no, x.pack.product_id, x.pack.product.category_id, x.pack.product.brand_id,
                  x.pack.product.is_rx_only or bool(x.pack.product.controlled_schedule), x.qty, x.qty_base,
                  x.line_total) for x in priceable])  # fmt: skip
    for x in priceable:
        x.promo_discount = result.discounts.get(x.line_no, ZERO)
        x.promotion_ids = [str(p) for p in result.promotions.get(x.line_no, [])]


def apply_manual(lines: list[PricedLine], raw: list[dict[str, Any]]) -> None:
    for x, item in zip(lines, raw, strict=True):
        left = x.line_total - x.promo_discount
        if item.get("discount_pct") is not None:
            x.manual_discount = min(cents(left * Decimal(str(item["discount_pct"])) / 100), left)
        elif item.get("discount_amount") is not None:
            x.manual_discount = min(money.usd(Decimal(str(item["discount_amount"]))), left)


async def price_cart(session: AsyncSession, branch_id: UUID, customer: KnownCustomer | None,
                     raw: list[dict[str, Any]]) -> list[PricedLine]:  # fmt: skip
    lines = [price_line(i, await pack_for(session, x["medicine_id"], x["pack_unit_id"], i), x["qty"])
             for i, x in enumerate(raw, start=1)]  # fmt: skip
    await apply_promotions(session, branch_id, customer, lines)
    apply_manual(lines, raw)
    return lines


def over_cap(caps: dict[str, int], role: str, lines: list[PricedLine]) -> Decimal | None:
    """The highest manual discount % above the role's cap, else None (the owner has no cap)."""
    if role == "owner":
        return None
    cap = Decimal(str(caps.get(role, 0)))
    worst = None
    for x in lines:
        base = x.line_total - x.promo_discount
        if x.manual_discount > 0 and base > 0:
            pct = (x.manual_discount * 100 / base).quantize(Decimal("0.01"))
            if pct > cap and (worst is None or pct > worst):
                worst = pct
    return worst


async def approve_discount(session: AsyncSession, actor: CurrentUser, auth: InternalClient, branch_id: UUID,
                           lines: list[PricedLine], token: str | None) -> UUID | None:  # fmt: skip
    """None when every manual discount is within the seller's cap; else the approver's id."""
    settings = await session.get(BranchSettingsCopy, branch_id)
    caps = settings.max_discount_pct if settings and settings.max_discount_pct else DEFAULT_CAPS
    worst = over_cap(caps, actor.role, lines)
    if worst is None:
        return None
    roles = ("owner",) if actor.role == "branch_manager" else ("branch_manager", "owner")
    if not token:
        raise AppError(ErrorCode.DISCOUNT_APPROVAL_REQUIRED,
                       f"A {worst} % discount is above your cap of {caps.get(actor.role, 0)} %: "
                       f"{'the owner' if roles == ('owner',) else 'a manager'} confirms with their PIN",
                       status_code=403, details={"cap": caps.get(actor.role, 0), "asked": str(worst),
                                                 "approver_roles": list(roles)})  # fmt: skip
    approver = await consume_witness(auth, token, "sales.discount", actor=actor, branch_id=branch_id, roles=roles,
                                     permission="sales.discount")  # fmt: skip
    return approver.user_id
