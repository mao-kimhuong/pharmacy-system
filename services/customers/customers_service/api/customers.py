from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..models import Customer, CustomerGroup, CustomerPayment
from ..schemas.customers import (
    CustomerCreate,
    CustomerOut,
    CustomerPage,
    CustomerUpdate,
    DebtOut,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    PaymentCreate,
    PaymentOut,
    PaymentPage,
    ReasonRequest,
    StatementOut,
)
from ..services import customers as svc
from ..services import payments
from ..services.common import balance_of

router = APIRouter()
contacts = requires("contacts.customers")


async def _out(session: AsyncSession, c: Customer) -> CustomerOut:
    balance = await balance_of(session, c.id)
    return CustomerOut.model_validate(c).model_copy(
        update={"balance": balance, "available_credit": max(c.credit_limit - balance, 0)}
    )


@router.get("/customer-groups", response_model=list[GroupOut], tags=["customer groups"])
async def list_groups(
    include_inactive: bool = False,
    _: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> list[CustomerGroup]:
    """Always available; the menu item is hidden while the customer_groups switch is off."""
    return await svc.list_groups(session, include_inactive)


@router.post("/customer-groups", response_model=GroupOut, status_code=201, tags=["customer groups"])
async def create_group(
    body: GroupCreate, user: CurrentUser = Depends(contacts), session: AsyncSession = Depends(db.session)
) -> CustomerGroup:
    return await svc.create_group(session, user, body.model_dump())


@router.patch("/customer-groups/{group_id}", response_model=GroupOut, tags=["customer groups"])
async def update_group(
    group_id: UUID, body: GroupUpdate, user: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> CustomerGroup:  # fmt: skip
    return await svc.update_group(session, user, group_id, body.model_dump(exclude_unset=True))


@router.post("/customer-groups/{group_id}/deactivate", response_model=GroupOut, tags=["customer groups"])
async def deactivate_group(
    group_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> CustomerGroup:  # fmt: skip
    return await svc.set_group_active(session, user, group_id, False, body.reason)


@router.post("/customer-groups/{group_id}/activate", response_model=GroupOut, tags=["customer groups"])
async def activate_group(
    group_id: UUID, user: CurrentUser = Depends(contacts), session: AsyncSession = Depends(db.session)
) -> CustomerGroup:
    return await svc.set_group_active(session, user, group_id, True, None)


@router.get("/customers", response_model=CustomerPage, tags=["customers"])
async def list_customers(
    q: str | None = Query(default=None, max_length=100, description="name, Khmer name or phone"),
    group_id: UUID | None = None,
    include_inactive: bool = False,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> CustomerPage:
    items, total = await svc.list_customers(session, q, group_id, include_inactive, page, size)
    return CustomerPage(items=[await _out(session, c) for c in items], total=total, page=page, size=size)


@router.post("/customers", response_model=CustomerOut, status_code=201, tags=["customers"])
async def create_customer(
    body: CustomerCreate, user: CurrentUser = Depends(contacts), session: AsyncSession = Depends(db.session)
) -> CustomerOut:
    """A credit limit above 0 needs customers.credit_limit (owner, branch manager)."""
    return await _out(session, await svc.create_customer(session, user, body.model_dump()))


@router.get("/customers/{customer_id}", response_model=CustomerOut, tags=["customers"])
async def get_customer(
    customer_id: UUID, _: CurrentUser = Depends(contacts), session: AsyncSession = Depends(db.session)
) -> CustomerOut:
    return await _out(session, await svc.get_customer(session, customer_id))


@router.patch("/customers/{customer_id}", response_model=CustomerOut, tags=["customers"])
async def update_customer(
    customer_id: UUID, body: CustomerUpdate, user: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> CustomerOut:  # fmt: skip
    return await _out(
        session, await svc.update_customer(session, user, customer_id, body.model_dump(exclude_unset=True))
    )


@router.post("/customers/{customer_id}/deactivate", response_model=CustomerOut, tags=["customers"])
async def deactivate_customer(
    customer_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> CustomerOut:  # fmt: skip
    return await _out(session, await svc.set_customer_active(session, user, customer_id, False, body.reason))


@router.post("/customers/{customer_id}/activate", response_model=CustomerOut, tags=["customers"])
async def activate_customer(
    customer_id: UUID, user: CurrentUser = Depends(contacts), session: AsyncSession = Depends(db.session)
) -> CustomerOut:
    return await _out(session, await svc.set_customer_active(session, user, customer_id, True, None))


@router.get("/customers/{customer_id}/unpaid", response_model=list[DebtOut], tags=["customers"])
async def unpaid_invoices(
    customer_id: UUID, _: CurrentUser = Depends(contacts), session: AsyncSession = Depends(db.session)
) -> list:
    """Credit invoices not fully paid, oldest first (the order payments are applied)."""
    await svc.get_customer(session, customer_id)
    return await payments.open_debts(session, customer_id)


@router.get("/customers/{customer_id}/statement", response_model=StatementOut, tags=["customers"],
            response_model_by_alias=True)  # fmt: skip
async def statement(
    customer_id: UUID,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    _: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> StatementOut:
    return StatementOut.model_validate(await payments.statement(session, customer_id, date_from, date_to))


@router.get("/customer-payments", response_model=PaymentPage, tags=["customer payments"])
async def list_payments(
    customer_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> PaymentPage:
    items, total = await payments.list_payments(session, user, customer_id, page, size)
    return PaymentPage(items=[PaymentOut.model_validate(p) for p in items], total=total, page=page, size=size)


@router.post("/customer-payments", response_model=PaymentOut, status_code=201, tags=["customer payments"])
async def create_payment(
    body: PaymentCreate,
    _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> CustomerPayment:
    """Applied to the oldest unpaid credit invoices first. More than owed → CUSTOMER_OVERPAYMENT."""
    return await payments.create_payment(session, user, body.model_dump())


@router.post("/customer-payments/{payment_id}/cancel", response_model=PaymentOut, tags=["customer payments"])
async def cancel_payment(
    payment_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(contacts),
    session: AsyncSession = Depends(db.session),
) -> CustomerPayment:  # fmt: skip
    return await payments.cancel_payment(session, user, payment_id, body.reason)
