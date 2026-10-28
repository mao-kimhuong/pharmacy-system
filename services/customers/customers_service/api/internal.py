"""/internal/v1 – called by the sales service (sale saga), never through Traefik."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.customers import ChargeRequest, CreditResult, NumberRequest, ReverseRequest
from ..services import credit

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
