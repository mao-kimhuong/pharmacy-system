from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..models import SupplierPayment
from ..schemas.purchasing import (
    BalanceOut,
    PaymentCreate,
    PaymentOut,
    PaymentPage,
    ReasonRequest,
    ReceiptOut,
    ReceiptPage,
    StatementOut,
)
from ..services import payments as svc
from ..services import receiving
from .common import respond

router = APIRouter()
pay = requires("purchasing.pay")
money_view = requires_any("purchasing.pay", "purchasing.order")


@router.get("/receipts", response_model=ReceiptPage, tags=["receipts"])
async def list_receipts(
    supplier_id: UUID | None = None,
    branch_id: UUID | None = None,
    status: str | None = Query(default=None, pattern="^(open|paid)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(requires_any("purchasing.receive", "purchasing.order", "purchasing.pay")),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """Goods received = the suppliers' bills."""
    items, total = await svc.list_receipts(session, user, supplier_id, branch_id, status, page, size)
    page_out = ReceiptPage(
        items=[ReceiptOut.model_validate(r) for r in items], total=total, page=page, size=size
    )
    return respond(page_out, user)


@router.get("/receipts/{receipt_id}", response_model=ReceiptOut, tags=["receipts"])
async def get_receipt(
    receipt_id: UUID,
    user: CurrentUser = Depends(requires_any("purchasing.receive", "purchasing.order", "purchasing.pay")),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    return respond(ReceiptOut.model_validate(await receiving.get_receipt(session, user, receipt_id)), user)


@router.get("/supplier-payments", response_model=PaymentPage, tags=["supplier payments"])
async def list_payments(
    supplier_id: UUID | None = None,
    branch_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(pay),
    session: AsyncSession = Depends(db.session),
) -> PaymentPage:
    items, total = await svc.list_payments(session, user, supplier_id, branch_id, page, size)
    return PaymentPage(items=[PaymentOut.model_validate(p) for p in items], total=total, page=page, size=size)


@router.post("/supplier-payments", response_model=PaymentOut, status_code=201, tags=["supplier payments"])
async def create_payment(
    body: PaymentCreate,
    _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(pay),
    session: AsyncSession = Depends(db.session),
) -> SupplierPayment:
    """Applied to the branch's unpaid bills of this supplier, oldest first.
    More than owed → SUPPLIER_OVERPAYMENT."""
    return await svc.create_payment(session, user, body.model_dump())


@router.get("/supplier-payments/{payment_id}", response_model=PaymentOut, tags=["supplier payments"])
async def get_payment(
    payment_id: UUID, user: CurrentUser = Depends(pay), session: AsyncSession = Depends(db.session)
) -> SupplierPayment:
    return await svc.get_payment(session, user, payment_id)


@router.post("/supplier-payments/{payment_id}/cancel", response_model=PaymentOut, tags=["supplier payments"])
async def cancel_payment(
    payment_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(pay),
    session: AsyncSession = Depends(db.session),
) -> SupplierPayment:  # fmt: skip
    """The bills it paid are open again."""
    return await svc.cancel_payment(session, user, payment_id, body.reason)


@router.get("/suppliers/{supplier_id}/balance", response_model=BalanceOut, tags=["suppliers"])
async def supplier_balance(
    supplier_id: UUID, user: CurrentUser = Depends(money_view), session: AsyncSession = Depends(db.session)
) -> dict:
    """What is owed to the supplier, per branch you work in."""
    return await svc.balance(session, user, supplier_id)


@router.get("/suppliers/{supplier_id}/statement", response_model=StatementOut, tags=["suppliers"],
            response_model_by_alias=True)  # fmt: skip
async def supplier_statement(
    supplier_id: UUID,
    branch_id: UUID | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    user: CurrentUser = Depends(money_view),
    session: AsyncSession = Depends(db.session),
) -> StatementOut:
    data = await svc.statement(session, user, supplier_id, branch_id, date_from, date_to)
    return StatementOut.model_validate({**data, "from": data.pop("from"), "to": data.pop("to")})
