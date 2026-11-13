"""/internal/v1 – re-order lists in inventory create purchase requests here; a recall's
"return to supplier" creates a draft supplier return (S8b)."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.approvals import VIA_TELEGRAM, DecideIn, acting_user
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.purchasing import PRInternal, SupplierReturnInternal
from ..services import requests as svc
from ..services import supplier_returns

router = APIRouter()


@router.post("/purchase-requests")
async def create_request(
    body: PRInternal, caller: InternalCaller = Depends(internal_caller), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Once per source_ref (a re-order list)."""
    r = await svc.create_internal(session, body.model_dump(), caller.user_id)
    return {"request_id": str(r.id), "number": r.number, "status": r.status}


@router.post("/supplier-returns/from-recall")
async def from_recall(
    body: SupplierReturnInternal, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """A draft return for a recall line (inventory). Once per source_ref."""
    actor = CurrentUser(id=caller.user_id or uuid4(), role=caller.role or "system",
                        branch_ids=frozenset({body.branch_id}), is_pharmacist=False)  # fmt: skip
    r = await supplier_returns.create(session, actor, body.model_dump())
    return {"id": str(r.id), "number": r.number, "status": r.status}


@router.post("/purchase-requests/{request_id}/decide")
async def decide_purchase_request(request_id: UUID, body: DecideIn, caller: InternalCaller = Depends(internal_caller),
                                  session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """T2: approve / reject a submitted purchase request as the user who tapped (purchasing.request_approve,
    that branch; never with a controlled medicine on it)."""
    r = await svc.decide(session, acting_user(body.actor), request_id, body.decision,
                         body.reason if body.decision == "reject" else None, via=VIA_TELEGRAM)  # fmt: skip
    return {"status": r.status, "number": r.number}
