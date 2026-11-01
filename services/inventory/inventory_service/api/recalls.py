"""Recalls (S8b): block recalled lots, see where they are, return or destroy, close or lift."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.internal import InternalClient

from ..db import db
from ..models import Recall
from ..schemas.inventory import (
    LiftIn,
    RecallDestroyIn,
    RecallDetail,
    RecallIn,
    RecallOut,
    RecallReturned,
    ShrinkageOut,
)
from ..services import recalls
from ..services.clients import get_auth, get_purchasing
from .s5 import _out as shrinkage_out
from .s5 import respond

router = APIRouter(tags=["recalls"])
perm = requires("inventory.recall")


@router.post("/recalls", response_model=RecallOut, status_code=201)
async def start(
    body: RecallIn, user: CurrentUser = Depends(perm), _: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(db.session),
) -> Recall:  # fmt: skip
    """Block these lots at once: the owner in every branch, a branch manager in their own branches."""
    return await recalls.start(session, user, body.model_dump())


@router.get("/recalls", response_model=list[RecallOut])
async def list_recalls(
    status: str | None = None, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session)
) -> list[Recall]:
    return await recalls.list_recalls(session, user, status)


@router.get("/recalls/{recall_id}", response_model=RecallDetail)
async def detail(recall_id: UUID, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session)) -> dict:
    """Per branch and batch: on hand, in transit, on open transfers, what was done."""
    return await recalls.detail(session, user, recall_id)


@router.post("/recalls/{recall_id}/lines/{line_id}/return", response_model=RecallReturned, status_code=201)
async def return_line(
    recall_id: UUID, line_id: UUID, user: CurrentUser = Depends(perm), _: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(db.session), purchasing: InternalClient = Depends(get_purchasing),
) -> dict:  # fmt: skip
    """A draft supplier return (purchasing) of what is on hand; submit it there."""
    out = await recalls.return_line(session, user, purchasing, recall_id, line_id)
    return {"supplier_return_id": out["id"], "number": out["number"]}


@router.post("/recalls/{recall_id}/lines/{line_id}/destroy", response_model=ShrinkageOut, status_code=201)
async def destroy_line(
    recall_id: UUID, line_id: UUID, body: RecallDestroyIn, user: CurrentUser = Depends(perm),
    _: str = Depends(require_idempotency_key), session: AsyncSession = Depends(db.session),
    auth: InternalClient = Depends(get_auth),
) -> JSONResponse:  # fmt: skip
    """Written off as shrinkage, reason recalled (controlled: PIN + a manager/owner witness). Value only with cost."""
    s = await recalls.destroy_line(session, user, auth, recall_id, line_id, body.model_dump())
    return respond(shrinkage_out(s), user, 201)


@router.post("/recalls/{recall_id}/close", response_model=RecallOut)
async def close(recall_id: UUID, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session)) -> Recall:
    return await recalls.close(session, user, recall_id)


@router.post("/recalls/{recall_id}/lift", response_model=RecallOut)
async def lift(recall_id: UUID, body: LiftIn, user: CurrentUser = Depends(perm),
               session: AsyncSession = Depends(db.session)) -> Recall:  # fmt: skip
    """Owner: the recall was a mistake or is withdrawn; the stock is sellable again."""
    return await recalls.lift(session, user, recall_id, body.reason)
