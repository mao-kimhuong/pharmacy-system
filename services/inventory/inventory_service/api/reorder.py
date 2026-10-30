from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.internal import InternalClient

from ..db import db
from ..models import ReorderList, ReorderSetting
from ..schemas.inventory import (
    ReorderBulkIn,
    ReorderLinesIn,
    ReorderListOut,
    ReorderSettingIn,
    ReorderSettingOut,
)
from ..services import reorder
from ..services.clients import get_purchasing
from .inventory import respond

router = APIRouter(tags=["re-order"])
perm = requires("inventory.reorder_settings")


def out(rl: ReorderList, user: CurrentUser) -> JSONResponse:
    return respond(ReorderListOut.model_validate(rl), user)


@router.put("/reorder-settings", response_model=ReorderSettingOut)
async def set_setting(
    body: ReorderSettingIn, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session),
) -> ReorderSetting:  # fmt: skip
    """Min (reorder point), max, lead time, preferred supplier; empty = from sales."""
    return await reorder.set_setting(session, user, body.model_dump())


@router.post("/reorder-settings/bulk")
async def set_bulk(
    body: ReorderBulkIn, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """The same settings for every active medicine of a category at the branch."""
    return {"updated": await reorder.set_bulk(session, user, body.model_dump())}


@router.get("/reorder-settings", response_model=list[ReorderSettingOut])
async def list_settings(
    branch_id: UUID, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session),
) -> list[ReorderSetting]:  # fmt: skip
    return await reorder.list_settings(session, user, branch_id)


@router.post("/reorder-lists/run", response_model=ReorderListOut)
async def run(
    branch_id: UUID, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """Build the branch's re-order list now (the daily job does it at 00:30)."""
    return out(await reorder.run_branch(session, user, branch_id), user)


@router.get("/reorder-lists/latest", response_model=ReorderListOut)
async def latest(
    branch_id: UUID, user: CurrentUser = Depends(perm), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    return out(await reorder.latest(session, user, branch_id), user)


@router.post("/reorder-lists/{list_id}/purchase-requests", response_model=ReorderListOut)
async def purchase_requests(
    list_id: UUID, body: ReorderLinesIn, user: CurrentUser = Depends(perm),
    session: AsyncSession = Depends(db.session), purchasing: InternalClient = Depends(get_purchasing),
) -> JSONResponse:  # fmt: skip
    """One purchase request with the chosen lines (needs purchasing.request too)."""
    return out(await reorder.to_purchase_request(session, user, purchasing, list_id, body.line_ids), user)


@router.post("/reorder-lists/{list_id}/transfer-requests", response_model=ReorderListOut)
async def transfer_requests(
    list_id: UUID, body: ReorderLinesIn, user: CurrentUser = Depends(perm),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """Transfer requests to the suggested branch (or the one given); needs transfers.request."""
    return out(
        await reorder.to_transfer_requests(session, user, list_id, body.line_ids, body.source_branch_id), user
    )
