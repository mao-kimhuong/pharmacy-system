"""/internal/v1 of the stockcount service (service token; never through Traefik)."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.approvals import VIA_TELEGRAM, DecideIn, acting_user
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..services import counts
from ..services.clients import Clients, get_clients

router = APIRouter()


@router.post("/counts/{count_id}/decide")
async def decide_count(count_id: UUID, body: DecideIn, caller: InternalCaller = Depends(internal_caller),
                       session: AsyncSession = Depends(db.session), clients: Clients = Depends(get_clients)) -> dict:  # fmt: skip
    """T2: approve a stock take in review as the user who tapped (stockcount.approve; owner above the branch's
    limit; never with a controlled variance – that needs the PIN). Stock takes have no reject: send lines back in
    the app."""
    user = acting_user(body.actor)
    user.require("stockcount.approve")
    if body.decision != "approve":
        raise AppError(ErrorCode.VALIDATION_ERROR, "A stock take is sent back for recount in the app", status_code=422)
    c = await counts.approve(session, user, clients, count_id, None, via=VIA_TELEGRAM)
    return {"status": c.status, "number": c.number}
