"""Commission. Rules:

- Rules (commission.manage): % of the line's net value, or USD per base unit;
  for one medicine, a category, a brand or everything; optionally for one staff
  member (an override) and one branch; with start / end dates. The most specific
  rule wins: a staff override first, then medicine > category > brand > all.
- Earned when a sale completes, by the user who completed it, on each line's net
  value in USD after promotions and manual discounts (USD prices; payments in riel
  were converted at the rate stored on the invoice).
- A return or a cancel takes it back with negative lines (the same rule, the
  returned share), once per invoice line and source.
- Periods per branch and month (Asia/Phnom_Penh): open → closed → paid. A closed
  or paid period is locked: lines go to the next open period (made when needed).
- Report per staff and period with drill-down to the invoice lines:
  commission.view_own sees only themselves, commission.manage the branch.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import CommissionLine, CommissionPeriod, CommissionRule, Invoice, Product
from .common import audit, clean
from .pricing import cents

SCOPE_RANK = {"medicine": 3, "category": 2, "brand": 1, "all": 0}


def month_of(day: date) -> date:
    return day.replace(day=1)


def next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


# ---------------------------------------------------------------- rules


async def create_rule(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> CommissionRule:
    if data["scope"] != "all" and not data.get("target_id"):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Choose the medicine, category or brand", status_code=422)
    if data.get("ends_on") and data["ends_on"] < data["starts_on"]:
        raise AppError(ErrorCode.VALIDATION_ERROR, "ends_on is before starts_on", status_code=422)
    if data.get("branch_id"):
        actor.require_branch(data["branch_id"])
    elif not actor.is_owner:
        raise AppError(ErrorCode.FORBIDDEN, "Only the owner sets rules for every branch", status_code=403)
    rule = CommissionRule(name=clean(data["name"]), kind=data["kind"], value=data["value"], scope=data["scope"],
                          target_id=data.get("target_id") if data["scope"] != "all" else None,
                          staff_id=data.get("staff_id"), branch_id=data.get("branch_id"), starts_on=data["starts_on"],
                          ends_on=data.get("ends_on"), is_active=True, created_by=actor.id)  # fmt: skip
    session.add(rule)
    await session.flush()
    audit(session, actor, "commission_rule.created", "commission_rule", rule.id, branch_id=rule.branch_id, after={
        "name": rule.name, "kind": rule.kind, "value": str(rule.value), "scope": rule.scope,
        "staff": str(rule.staff_id) if rule.staff_id else None})  # fmt: skip
    await session.commit()
    return rule


async def set_rule_active(
    session: AsyncSession, actor: CurrentUser, rule_id: UUID, active: bool
) -> CommissionRule:
    rule = await session.get(CommissionRule, rule_id)
    if rule is None or (rule.branch_id and not actor.can_access_branch(rule.branch_id)):
        raise AppError(ErrorCode.NOT_FOUND, "Commission rule not found", status_code=404)
    if rule.is_active != active:
        rule.is_active = active
        audit(session, actor, "commission_rule." + ("activated" if active else "deactivated"), "commission_rule",
              rule.id, branch_id=rule.branch_id)  # fmt: skip
        await session.commit()
    return rule


async def list_rules(session: AsyncSession, actor: CurrentUser) -> list[CommissionRule]:
    query = select(CommissionRule)
    if not actor.is_owner:
        query = query.where(
            (CommissionRule.branch_id.is_(None)) | CommissionRule.branch_id.in_(list(actor.branch_ids))
        )
    return list((await session.execute(query.order_by(CommissionRule.created_at))).scalars())


async def rule_for(session: AsyncSession, branch_id: UUID, staff_id: UUID, product: Product, day: date
                   ) -> CommissionRule | None:  # fmt: skip
    rows = (await session.execute(select(CommissionRule).where(
        CommissionRule.is_active.is_(True), CommissionRule.starts_on <= day,
        (CommissionRule.ends_on.is_(None)) | (CommissionRule.ends_on >= day),
        (CommissionRule.branch_id.is_(None)) | (CommissionRule.branch_id == branch_id),
        (CommissionRule.staff_id.is_(None)) | (CommissionRule.staff_id == staff_id)))).scalars()  # fmt: skip
    matching = []
    for r in rows:
        target = {"medicine": product.id, "category": product.category_id, "brand": product.brand_id}.get(
            r.scope
        )
        if r.scope == "all" or (target is not None and r.target_id == target):
            matching.append(
                ((r.staff_id is not None, SCOPE_RANK[r.scope], r.branch_id is not None, r.created_at), r)
            )
    return max(matching, key=lambda m: m[0])[1] if matching else None


# ---------------------------------------------------------------- periods


async def open_period(session: AsyncSession, branch_id: UUID, day: date) -> CommissionPeriod:
    """The period of that day's month, or the next open one when it is locked."""
    month = month_of(day)
    while True:
        await session.execute(insert(CommissionPeriod).values(branch_id=branch_id, month=month, status="open")
                              .on_conflict_do_nothing())  # fmt: skip
        period = (await session.execute(select(CommissionPeriod).where(
            CommissionPeriod.branch_id == branch_id, CommissionPeriod.month == month))).scalar_one()  # fmt: skip
        if period.status == "open":
            return period
        month = next_month(month)


async def set_period(session: AsyncSession, actor: CurrentUser, branch_id: UUID, month: date, status: str
                     ) -> CommissionPeriod:  # fmt: skip
    actor.require_branch(branch_id)
    await session.execute(insert(CommissionPeriod).values(branch_id=branch_id, month=month_of(month), status="open")
                          .on_conflict_do_nothing())  # fmt: skip
    period = (await session.execute(select(CommissionPeriod).where(
        CommissionPeriod.branch_id == branch_id, CommissionPeriod.month == month_of(month)).with_for_update())).scalar_one()  # fmt: skip
    allowed = {"closed": ("open",), "paid": ("closed",)}[status]
    if period.status not in allowed:
        raise AppError(ErrorCode.PERIOD_LOCKED, f"The period is {period.status}", status_code=409,
                       details={"status": period.status})  # fmt: skip
    period.status = status
    if status == "closed":
        period.closed_by, period.closed_at = actor.id, clock.now()
    else:
        period.paid_by, period.paid_at = actor.id, clock.now()
    audit(session, actor, f"commission_period.{status}", "commission_period", period.id, branch_id=branch_id,
          after={"month": period.month.isoformat()})  # fmt: skip
    await session.commit()
    return period


# ---------------------------------------------------------------- earning and taking back


async def record_sale(session: AsyncSession, inv: Invoice) -> int:
    """At completion (the caller's transaction): one line per invoice line with a rule."""
    day = inv.completed_at.astimezone(clock.TIMEZONE).date() if inv.completed_at else clock.today()
    period = await open_period(session, inv.branch_id, day)
    made = 0
    for line in inv.lines:
        product = await session.get(Product, line.medicine_id)
        rule = await rule_for(session, inv.branch_id, inv.created_by, product, day) if product else None
        if rule is None:
            continue
        amount = (
            cents(line.net * rule.value / 100)
            if rule.kind == "percent"
            else cents(rule.value * line.qty_base)
        )
        if amount == 0:
            continue
        result = await session.execute(insert(CommissionLine).values(
            period_id=period.id, branch_id=inv.branch_id, staff_id=inv.created_by, invoice_id=inv.id,
            invoice_line_id=line.id, invoice_number=inv.number or "", source="sale", medicine_id=line.medicine_id,
            sku=line.sku, qty_base=line.qty_base, net_usd=line.net, rule_id=rule.id, amount=amount,
        ).on_conflict_do_nothing())  # fmt: skip
        made += result.rowcount or 0
    return made


async def take_back(
    session: AsyncSession, inv: Invoice, source: str, returned: dict[UUID, int] | None = None
) -> int:
    """Return (line id → base units returned) or cancel (None: everything): negative
    lines in the open period of today, once per line and source."""
    sales = list((await session.execute(select(CommissionLine).where(
        CommissionLine.invoice_id == inv.id, CommissionLine.source == "sale"))).scalars())  # fmt: skip
    if not sales:
        return 0
    period = await open_period(session, inv.branch_id, clock.today())
    made = 0
    for s in sales:
        qty = s.qty_base if returned is None else returned.get(s.invoice_line_id, 0)
        if qty <= 0:
            continue
        already = (await session.execute(select(func.coalesce(func.sum(CommissionLine.amount), 0)).where(
            CommissionLine.invoice_line_id == s.invoice_line_id, CommissionLine.source != "sale"))).scalar_one()  # fmt: skip
        amount = -min(cents(s.amount * qty / s.qty_base), s.amount + Decimal(already))
        if amount == 0:
            continue
        result = await session.execute(insert(CommissionLine).values(
            period_id=period.id, branch_id=s.branch_id, staff_id=s.staff_id, invoice_id=s.invoice_id,
            invoice_line_id=s.invoice_line_id, invoice_number=s.invoice_number, source=source,
            medicine_id=s.medicine_id, sku=s.sku, qty_base=-qty, net_usd=-cents(s.net_usd * qty / s.qty_base),
            rule_id=s.rule_id, amount=amount,
        ).on_conflict_do_nothing())  # fmt: skip
        made += result.rowcount or 0
    return made


# ---------------------------------------------------------------- report


def _scope(actor: CurrentUser, branch_id: UUID, staff_id: UUID | None) -> UUID | None:
    actor.require_branch(branch_id)
    if actor.has("commission.manage"):
        return staff_id
    actor.require("commission.view_own")
    if staff_id and staff_id != actor.id:
        raise AppError(ErrorCode.FORBIDDEN, "You can see only your own commission", status_code=403)
    return actor.id


async def report(session: AsyncSession, actor: CurrentUser, branch_id: UUID, month: date,
                 staff_id: UUID | None = None) -> dict[str, Any]:  # fmt: skip
    staff = _scope(actor, branch_id, staff_id)
    period = (await session.execute(select(CommissionPeriod).where(
        CommissionPeriod.branch_id == branch_id, CommissionPeriod.month == month_of(month)))).scalar_one_or_none()  # fmt: skip
    rows: list[Any] = []
    if period:
        query = (select(CommissionLine.staff_id, func.sum(CommissionLine.net_usd), func.sum(CommissionLine.amount),
                        func.count()).where(CommissionLine.period_id == period.id)
                 .group_by(CommissionLine.staff_id))  # fmt: skip
        if staff:
            query = query.where(CommissionLine.staff_id == staff)
        rows = (await session.execute(query)).all()
    return {"branch_id": branch_id, "month": month_of(month), "status": period.status if period else "open",
            "staff": [{"staff_id": s, "net_usd": str(n), "commission": str(a), "lines": c} for s, n, a, c in rows],
            "total": str(sum((a for _, _, a, _ in rows), Decimal("0.00")))}  # fmt: skip


async def drill_down(session: AsyncSession, actor: CurrentUser, branch_id: UUID, month: date, staff_id: UUID
                     ) -> list[CommissionLine]:  # fmt: skip
    staff = _scope(actor, branch_id, staff_id)
    period = (await session.execute(select(CommissionPeriod).where(
        CommissionPeriod.branch_id == branch_id, CommissionPeriod.month == month_of(month)))).scalar_one_or_none()  # fmt: skip
    if period is None:
        return []
    return list((await session.execute(select(CommissionLine).where(
        CommissionLine.period_id == period.id, CommissionLine.staff_id == staff)
        .order_by(CommissionLine.created_at, CommissionLine.invoice_number))).scalars())  # fmt: skip
