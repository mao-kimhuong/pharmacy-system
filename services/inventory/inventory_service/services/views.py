"""Stock, batch and movement views (inventory.view). Rules:

- Staff see only their branches; the owner sees all (and may leave branch_id
  out for every branch).
- Batches are listed FEFO: expiry date, then received date.
- Totals in base units and broken down into pack units (e.g. 12 box + 5 strip).
- Cost per base unit and stock value only with finance.cost_profit (the route
  drops those fields for everyone else).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import Batch, Movement, Product, Stock
from .common import clean

CENT = Decimal("0.01")
FEFO = (Batch.expiry_date, Batch.received_at, Batch.id)


def _branches(actor: CurrentUser, branch_id: UUID | None) -> list[UUID] | None:
    """Branch ids to filter on; None = all (owner only)."""
    if branch_id is not None:
        if not actor.can_access_branch(branch_id):
            raise AppError(ErrorCode.BRANCH_FORBIDDEN, "No access to this branch", status_code=403)
        return [branch_id]
    if actor.is_owner:
        return None
    return list(actor.branch_ids) or [UUID(int=0)]


def in_packs(qty_base: int, product: Product | None) -> list[dict[str, Any]]:
    """12 box + 5 strip + 3 tablet: largest active pack unit first."""
    if product is None:
        return [{"pack_unit": "", "qty": qty_base}]
    left, out = qty_base, []
    for pack in sorted((p for p in product.pack_units if p.is_active), key=lambda p: -p.qty_in_base):
        n, left = divmod(left, pack.qty_in_base)
        if n:
            out.append({"pack_unit": pack.name, "qty": n})
    return out


def _batch_row(stock: Stock, today: date) -> dict[str, Any]:
    b = stock.batch
    return {
        "batch_id": b.id, "lot_no": b.lot_no, "expiry_date": b.expiry_date,
        "days_to_expiry": (b.expiry_date - today).days, "status": b.status, "received_at": b.received_at,
        "supplier_id": b.supplier_id, "qty_on_hand": stock.qty_on_hand, "qty_reserved": stock.qty_reserved,
        "qty_available": stock.qty_on_hand - stock.qty_reserved if b.status == "active" else 0,
        "cost_per_base": b.cost_per_base, "value": (b.cost_per_base * stock.qty_on_hand).quantize(CENT),
    }  # fmt: skip


@dataclass(frozen=True)
class StockFilter:
    branch_id: UUID | None = None
    medicine_id: UUID | None = None
    q: str | None = None


async def stock(
    session: AsyncSession, actor: CurrentUser, f: StockFilter, page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """One item per branch + medicine with stock, its batches FEFO."""
    branches = _branches(actor, f.branch_id)
    cond = [Stock.qty_on_hand > 0]
    if branches is not None:
        cond.append(Stock.branch_id.in_(branches))
    if f.medicine_id:
        cond.append(Batch.medicine_id == f.medicine_id)
    groups = (
        select(Stock.branch_id, Batch.medicine_id)
        .join(Batch, Batch.id == Stock.batch_id)
        .outerjoin(Product, Product.id == Batch.medicine_id)
        .where(*cond)
    )
    if f.q and clean(f.q):
        like = "%" + clean(f.q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        groups = groups.where(or_(Product.sku.ilike(like, escape="\\"), Product.brand_name.ilike(like, escape="\\"),
                                  Product.generic_name.ilike(like, escape="\\"), Product.name_km.ilike(like, escape="\\")))  # fmt: skip
    groups = groups.group_by(Stock.branch_id, Batch.medicine_id, Product.sku)
    total = (await session.execute(select(func.count()).select_from(groups.subquery()))).scalar_one()
    keys = (
        await session.execute(
            groups.order_by(Product.sku, Stock.branch_id).offset((page - 1) * size).limit(size)
        )
    ).all()
    if not keys:
        return [], int(total)
    rows = (
        await session.execute(
            select(Stock).join(Batch, Batch.id == Stock.batch_id)
            .where(Stock.qty_on_hand > 0, or_(*(and_(Stock.branch_id == b, Batch.medicine_id == m) for b, m in keys)))
            .order_by(*FEFO)
        )
    ).scalars().all()  # fmt: skip
    products = {
        p.id: p
        for p in (
            await session.execute(select(Product).where(Product.id.in_({m for _, m in keys})))
        ).scalars()
    }
    today = clock.today()
    items = []
    for branch_id, medicine_id in keys:
        batches = [
            _batch_row(s, today)
            for s in rows
            if s.branch_id == branch_id and s.batch.medicine_id == medicine_id
        ]
        product = products.get(medicine_id)
        on_hand = sum(b["qty_on_hand"] for b in batches)
        available = sum(b["qty_available"] for b in batches)
        items.append({
            "branch_id": branch_id, "medicine_id": medicine_id, "sku": product.sku if product else "",
            "name": product.display_name if product else "", "name_km": product.name_km if product else "",
            "base_unit": product.base_unit if product else "",
            "controlled_schedule": product.controlled_schedule if product else None,
            "qty_on_hand": on_hand, "qty_reserved": sum(b["qty_reserved"] for b in batches), "qty_available": available,
            "on_hand_in_packs": in_packs(on_hand, product), "available_in_packs": in_packs(available, product),
            "stock_value": sum((b["value"] for b in batches), Decimal("0.00")), "batches": batches,
        })  # fmt: skip
    return items, int(total)


async def batches(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID | None, medicine_id: UUID | None,
    expiring_within: int | None, status: str | None, page: int, size: int,
) -> tuple[list[dict[str, Any]], int]:  # fmt: skip
    """Batches with stock at your branches, earliest expiry first."""
    branches = _branches(actor, branch_id)
    query = select(Stock).join(Batch, Batch.id == Stock.batch_id).where(Stock.qty_on_hand > 0)
    if branches is not None:
        query = query.where(Stock.branch_id.in_(branches))
    if medicine_id:
        query = query.where(Batch.medicine_id == medicine_id)
    today = clock.today()
    if expiring_within is not None:
        query = query.where(Batch.expiry_date <= today + timedelta(days=expiring_within))
    if status:
        query = query.where(Batch.status == status)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        (await session.execute(query.order_by(*FEFO, Stock.branch_id).offset((page - 1) * size).limit(size)))
        .scalars()
        .all()
    )
    products = {
        p.id: p
        for p in (
            await session.execute(select(Product).where(Product.id.in_({s.batch.medicine_id for s in rows})))
        ).scalars()
    }
    items = []
    for s in rows:
        product = products.get(s.batch.medicine_id)
        items.append({
            "branch_id": s.branch_id, "medicine_id": s.batch.medicine_id, "sku": product.sku if product else "",
            "name": product.display_name if product else "", **_batch_row(s, today),
            "on_hand_in_packs": in_packs(s.qty_on_hand, product),
        })  # fmt: skip
    return items, int(total)


async def movements(
    session: AsyncSession, actor: CurrentUser, branch_id: UUID | None, batch_id: UUID | None,
    medicine_id: UUID | None, type: str | None, date_from: date | None, date_to: date | None, page: int, size: int,
) -> tuple[list[Movement], int]:  # fmt: skip
    branches = _branches(actor, branch_id)
    query = select(Movement)
    if branches is not None:
        query = query.where(Movement.branch_id.in_(branches))
    if batch_id:
        query = query.where(Movement.batch_id == batch_id)
    if medicine_id:
        query = query.where(Movement.medicine_id == medicine_id)
    if type:
        query = query.where(Movement.type == type)
    if date_from:
        query = query.where(func.timezone("Asia/Phnom_Penh", Movement.created_at) >= date_from)
    if date_to:
        query = query.where(
            func.timezone("Asia/Phnom_Penh", Movement.created_at) < date_to + timedelta(days=1)
        )
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(Movement.seq.desc()).offset((page - 1) * size).limit(size))
    return list(rows.scalars()), int(total)
