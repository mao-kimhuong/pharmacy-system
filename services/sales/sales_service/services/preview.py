"""POST /carts/preview: what posting this cart would do, without doing anything.
Same checks as the sale (checks.run_checks in collect mode), then the read-only
twins of the saga's later steps. Writes nothing: no invoice, no outbox, no
promotion use, no Rx hold, no reservation, no PIN consumed.

can_post = lines, no hard stop and every warning resolved (requirements, such as
the pharmacist's PIN, are assumed to be supplied when posting)."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser

from ..models import PromotionCopy
from . import checks, money, promotions
from .clients import Clients
from .pricing import PriceLine


async def _names(session: AsyncSession, ids: set[str], draft: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    out = {}
    if ids:
        rows = (await session.execute(select(PromotionCopy).where(PromotionCopy.id.in_([UUID(i) for i in ids]))))
        out = {str(r.id): {"code": r.code, "name_en": r.data.get("name") or r.code, "name_km": r.data.get("name_km") or ""}
               for r in rows.scalars()}  # fmt: skip
    if draft is not None:
        out[str(draft["promotion_id"])] = {"code": draft["code"], "name_en": draft.get("name") or draft["code"],
                                           "name_km": draft.get("name_km") or ""}  # fmt: skip
    return out


async def _conflicts(session: AsyncSession, result: checks.CheckResult, draft: dict[str, Any],
                     names: dict[str, dict[str, str]]) -> list[dict[str, Any]]:  # fmt: skip
    """Per line: every promotion that targets it (the draft included) and which won."""
    promos = [p for p in await promotions.applicable(session, result.branch.id, result.customer)
              if str(p.id) != str(draft["promotion_id"])]  # fmt: skip
    if promotions.eligible(draft, result.branch.id, result.customer):
        promos.append(promotions.draft_promo(draft))
    out = []
    for x in result.lines:
        p = x.pack.product
        line = PriceLine(x.line_no, p.id, p.category_id, p.brand_id, p.is_rx_only or bool(p.controlled_schedule), x.qty,
                         x.qty_base, x.line_total)  # fmt: skip
        targets = [q for q in promos if q.targets(line)]
        if len(targets) > 1 or (targets and str(targets[0].id) == str(draft["promotion_id"]) and x.promotion_ids
                                and str(draft["promotion_id"]) not in x.promotion_ids):  # fmt: skip
            out.append({"line_no": x.line_no, "promotions": sorted(q.code for q in targets),
                        "applied": [names.get(i, {}).get("code", i) for i in x.promotion_ids],
                        "draft_wins": str(draft["promotion_id"]) in x.promotion_ids})  # fmt: skip
    return out


async def preview(session: AsyncSession, actor: CurrentUser, clients: Clients, data: dict[str, Any],
                  draft: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    result = await checks.run_checks(session, actor, clients, data, "collect", draft=draft)
    c = result.checks
    await checks.preview_rx(clients, actor, result.branch.id, result.lines, c)
    batches = await checks.preview_stock(clients, actor, result.branch.id, result.lines, c)
    await checks.preview_credit(clients, actor, result, c)
    names = await _names(session, {i for x in result.lines for i in x.promotion_ids}, draft)
    see_cost = actor.is_owner or actor.has("finance.cost_profit")

    planned = {x.line_no for x in result.lines}

    def mine(line_no: int | None, *severities: str) -> list[dict[str, Any]]:
        """A line's findings; None: the cart's, and those of lines that could not be planned."""
        return [f.out() for f in c.findings if f.severity in severities
                and (f.line_no == line_no or (line_no is None and f.line_no not in planned))]  # fmt: skip

    lines = []
    for x in result.lines:
        lines.append({
            "line_no": x.line_no, "medicine_id": x.pack.product_id, "pack_unit_id": x.pack.id,
            "sku": x.pack.product.sku, "name": x.pack.product.display_name, "pack_unit": x.pack.name, "qty": x.qty,
            "unit_price": x.unit_price, "line_total": x.line_total,
            "promotions": [{"id": i, **names.get(i, {"code": i, "name_en": i, "name_km": ""}),
                            "discount": x.promotion_amounts.get(i, Decimal("0.00"))} for i in x.promotion_ids],
            "promo_discount": x.promo_discount, "manual_discount": x.manual_discount, "net": x.net,
            "batches": [{"lot_no": b["lot_no"], "expiry_date": b["expiry_date"], "qty_base": b["qty_base"],
                         **({"cost_per_base": b["cost_per_base"]} if see_cost else {})}
                        for b in batches.get(x.line_no, [])],
            "hard_stops": mine(x.line_no, "hard_stop"), "requirements": mine(x.line_no, "requirement"),
            "warnings": mine(x.line_no, "warning", "info"),
        })  # fmt: skip
    rate = result.rate.khr_per_usd if result.rate else None
    exact = result.total * rate if rate else None
    total_khr = money.round_riel(exact) if rate else None
    out = {
        "branch_id": result.branch.id, "customer_id": result.customer.id if result.customer else None,
        "lines": lines, "subtotal": result.subtotal, "discount": result.discount, "total": result.total,
        "khr_per_usd": rate, "total_khr": total_khr,
        "rounding_khr": (Decimal(total_khr) - exact).quantize(Decimal("0.01")) if rate else None,
        "hard_stops": mine(None, "hard_stop"), "requirements": mine(None, "requirement"),
        "warnings": mine(None, "warning", "info"),
        "can_post": bool(lines) and len(lines) == len(data["lines"]) and not c.blocking,
    }  # fmt: skip
    if result.settlement is not None:
        s = result.settlement
        out["payment"] = {"paid": s.paid, "credit": s.credit, "change_usd": s.change_usd,
                          "change_given_usd": s.change_given_usd, "change_given_khr": s.change_given_khr}  # fmt: skip
    if draft is not None:
        out["conflicts"] = await _conflicts(session, result, draft, names)
    await session.rollback()  # nothing of this is kept
    return out
