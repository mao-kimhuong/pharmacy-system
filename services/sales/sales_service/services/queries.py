"""List Sale and invoice detail. Staff see only their branches (others: 404)."""

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import Invoice, SaleReturn
from .common import clean


async def get_invoice(
    session: AsyncSession, actor: CurrentUser, invoice_id: UUID, *, lock: bool = False
) -> Invoice:
    query = select(Invoice).where(Invoice.id == invoice_id)
    inv = (await session.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
    if inv is None or not actor.can_access_branch(inv.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Invoice not found", status_code=404)
    return inv


async def returns_of(session: AsyncSession, invoice_id: UUID) -> list[SaleReturn]:
    return list((await session.execute(select(SaleReturn).where(SaleReturn.invoice_id == invoice_id)
                                       .order_by(SaleReturn.created_at))).scalars())  # fmt: skip


@dataclass(frozen=True)
class InvoiceFilter:
    date_from: date | None = None
    date_to: date | None = None
    branch_id: UUID | None = None
    staff_id: UUID | None = None
    customer_id: UUID | None = None
    status: str | None = None
    number: str | None = None


async def list_invoices(
    session: AsyncSession, actor: CurrentUser, f: InvoiceFilter, page: int, size: int
) -> tuple[list[Invoice], int]:
    query = select(Invoice)
    if not actor.is_owner:
        query = query.where(Invoice.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
    local = func.timezone("Asia/Phnom_Penh", Invoice.created_at)
    if f.date_from:
        query = query.where(local >= f.date_from)
    if f.date_to:
        query = query.where(local < f.date_to + timedelta(days=1))
    if f.branch_id:
        query = query.where(Invoice.branch_id == f.branch_id)
    if f.staff_id:
        query = query.where(Invoice.created_by == f.staff_id)
    if f.customer_id:
        query = query.where(Invoice.customer_id == f.customer_id)
    if f.status:
        query = query.where(Invoice.status == f.status)
    if f.number and clean(f.number):
        query = query.where(Invoice.number.ilike(f"%{clean(f.number).replace('%', '').replace('_', '')}%"))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(Invoice.created_at.desc(), Invoice.id)
                                 .offset((page - 1) * size).limit(size))  # fmt: skip
    return list(rows.scalars()), int(total)
