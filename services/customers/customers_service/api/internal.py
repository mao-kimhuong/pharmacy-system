"""/internal/v1 – called by the sales service (sale saga), never through Traefik."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.customers import (
    ChargeRequest,
    CreditResult,
    CreditStatus,
    DepositSettle,
    DepositTake,
    DepositUse,
    NumberRequest,
    ReverseRequest,
    StatementOut,
)
from ..services import credit, deposits, payments

router = APIRouter()


@router.get("/customers/{customer_id}/credit", response_model=CreditStatus)
async def credit_status(
    customer_id: UUID, caller: InternalCaller = Depends(internal_caller), session: AsyncSession = Depends(db.session)
) -> dict:
    """The cart preview's credit check: balance, limit, what is still available."""
    return await credit.credit_status(session, customer_id)


@router.get("/customers/{customer_id}/statement", response_model=StatementOut, response_model_by_alias=True)
async def statement(
    customer_id: UUID, date_from: date | None = None, date_to: date | None = None,
    caller: InternalCaller = Depends(internal_caller), session: AsyncSession = Depends(db.session),
) -> StatementOut:  # fmt: skip
    """The statement for the document service (customer statement PDF)."""
    return StatementOut.model_validate(await payments.statement(session, customer_id, date_from, date_to))


@router.post("/credit/charge", response_model=CreditResult)
async def charge(
    body: ChargeRequest,
    caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """Credit limit check + ledger charge; once per invoice."""
    return await credit.charge(session, caller, body.model_dump())


@router.post("/credit/reverse", response_model=CreditResult)
async def reverse(
    body: ReverseRequest,
    caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """Undo an invoice's charge (cancel) or give a credit note (return); once per ref."""
    return await credit.reverse(session, caller, body.model_dump())


@router.post("/credit/number")
async def number(
    body: NumberRequest,
    _: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """The completed sale's number onto its debt (the charge came before the number)."""
    return {"updated": await credit.set_invoice_number(session, body.invoice_id, body.invoice_no)}


# ---------------------------------------------------------------- deposits (S7: sale orders)


@router.post("/deposits")
async def take_deposit(
    body: DepositTake, caller: InternalCaller = Depends(internal_caller), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Once per sale order (ref)."""
    return await deposits.take(session, caller, body.model_dump())


@router.post("/deposits/{deposit_id}/use")
async def use_deposit(
    deposit_id: UUID, body: DepositUse, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """An invoice pays with the deposit; once per invoice. DEPOSIT_EXCEEDED above what is left."""
    return await deposits.use(session, caller, deposit_id, body.model_dump())


@router.post("/deposits/{deposit_id}/unuse")
async def unuse_deposit(
    deposit_id: UUID, body: DepositUse, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """The invoice was undone or cancelled: its part goes back on the deposit."""
    return await deposits.unuse(session, caller, deposit_id, body.model_dump())


@router.post("/deposits/{deposit_id}/settle")
async def settle_deposit(
    deposit_id: UUID, body: DepositSettle, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """The order ended: what is left is kept as credit, refunded or forfeited."""
    return await deposits.settle(session, caller, deposit_id, body.model_dump())
