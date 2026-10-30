"""/internal/v1 – re-order lists in inventory create purchase requests here."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.purchasing import PRInternal
from ..services import requests as svc

router = APIRouter()


@router.post("/purchase-requests")
async def create_request(
    body: PRInternal, caller: InternalCaller = Depends(internal_caller), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Once per source_ref (a re-order list)."""
    r = await svc.create_internal(session, body.model_dump(), caller.user_id)
    return {"request_id": str(r.id), "number": r.number, "status": r.status}
