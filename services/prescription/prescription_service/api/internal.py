"""/internal/v1 – called by the sales service (sale saga), never through Traefik."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.rx import HoldOut, HoldRequest, ReleaseOut, ReleaseRequest
from ..services import dispensing

router = APIRouter()


@router.post("/rx/check-and-hold", response_model=HoldOut)
async def check_and_hold(
    body: HoldRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Checks every Rx line (state, date, quantity, allergy, duplicate therapy) and
    holds the quantity for the sale. Idempotent per invoice."""
    return await dispensing.check_and_hold(session, caller, body.model_dump())


@router.post("/rx/release", response_model=ReleaseOut)
async def release(
    body: ReleaseRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Saga compensation: the sale did not complete. Nothing held → nothing to do."""
    return await dispensing.release(session, caller, body.invoice_id)
