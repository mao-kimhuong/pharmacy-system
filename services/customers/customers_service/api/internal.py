"""/internal/v1 – called by the sales service (sale saga), never through Traefik."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.customers import (
    ChargeRequest,
    CreditResult,
    DepositSettle,
    DepositTake,
    DepositUse,
    NumberRequest,
    ReverseRequest,
)
from ..services import credit, deposits

router = APIRouter()


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
