from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient

from ..db import db
from ..models import POGroup, PurchaseOrder, PurchaseRequest
from ..schemas.purchasing import FillByTransfer, POGroupOut, POOut, PRCreate, PRDecision, PROut, ToPO
from ..services import requests as svc
from ..services.clients import get_inventory
from .common import respond

router = APIRouter(tags=["purchase requests"])
see = requires_any("purchasing.request", "purchasing.request_approve", "purchasing.order")


def out(r: PurchaseRequest) -> dict[str, Any]:
    data = PROut.model_validate(r)
    data.progress = svc.progress(r)
    return data.model_dump(mode="json")


@router.post("/purchase-requests", response_model=PROut, status_code=201)
async def create(
    body: PRCreate, user: CurrentUser = Depends(requires("purchasing.request")),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Your branch asks for medicines (quantity in the base unit, reason, needed-by date)."""
    return out(await svc.create(session, user, body.model_dump()))


@router.get("/purchase-requests", response_model=list[PROut])
async def list_requests(
    branch_id: UUID | None = None, status: str | None = Query(default=None, max_length=10),
    user: CurrentUser = Depends(see), session: AsyncSession = Depends(db.session),
) -> list[dict]:  # fmt: skip
    return [out(r) for r in await svc.list_requests(session, user, branch_id, status)]


@router.get("/purchase-requests/{request_id}", response_model=PROut)
async def get_request(
    request_id: UUID, user: CurrentUser = Depends(see), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """With each line's progress: PO number or transfer number, and how much arrived."""
    return out(await svc.get_request(session, user, request_id))


@router.post("/purchase-requests/{request_id}/approve", response_model=PROut)
async def approve(
    request_id: UUID, user: CurrentUser = Depends(requires("purchasing.request_approve")),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    return out(await svc.decide(session, user, request_id, "approve"))


@router.post("/purchase-requests/{request_id}/reject", response_model=PROut)
async def reject(
    request_id: UUID, body: PRDecision, user: CurrentUser = Depends(requires("purchasing.request_approve")),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    return out(await svc.decide(session, user, request_id, "reject", body.reason))


@router.post("/purchase-requests/{request_id}/cancel", response_model=PROut)
async def cancel(
    request_id: UUID, body: PRDecision, user: CurrentUser = Depends(requires("purchasing.request")),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    return out(await svc.decide(session, user, request_id, "cancel", body.reason))


@router.post("/purchase-requests/{request_id}/fill-by-transfer", response_model=PROut)
async def fill_by_transfer(
    request_id: UUID, body: FillByTransfer, user: CurrentUser = Depends(requires("purchasing.request_approve")),
    session: AsyncSession = Depends(db.session), inventory: InternalClient = Depends(get_inventory),
) -> dict:  # fmt: skip
    """Approved lines are sent by another branch: an approved transfer is made there."""
    return out(await svc.fill_by_transfer(session, user, inventory, request_id, body.model_dump()))


@router.post("/purchase-requests/to-purchase-orders", response_model=POGroupOut, status_code=201)
async def to_purchase_orders(
    body: ToPO, user: CurrentUser = Depends(requires("purchasing.order")),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """Approved lines of one or more branches, one supplier: one draft PO per branch,
    linked by a group number (print the group for the supplier)."""
    group = await svc.to_purchase_orders(session, user, body.model_dump())
    return await group_out(session, user, group, 201)


async def group_out(session: AsyncSession, user: CurrentUser, group: POGroup, status_code: int = 200) -> JSONResponse:
    pos = list((await session.execute(select(PurchaseOrder).where(PurchaseOrder.group_id == group.id)
                                      .order_by(PurchaseOrder.number))).scalars())  # fmt: skip
    data = POGroupOut.model_validate(group)
    data.purchase_orders = [POOut.model_validate(po) for po in pos if user.can_access_branch(po.branch_id)]
    return respond(data, user, status_code)


@router.get("/po-groups/{group_id}", response_model=POGroupOut)
async def get_group(
    group_id: UUID, user: CurrentUser = Depends(requires("purchasing.order")),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    group = await session.get(POGroup, group_id)
    if group is None:
        raise AppError(ErrorCode.NOT_FOUND, "PO group not found", status_code=404)
    return await group_out(session, user, group)
