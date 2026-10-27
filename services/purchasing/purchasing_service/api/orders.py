from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..schemas.purchasing import POCreate, POOut, POPage, POUpdate, ReasonRequest, ReceiptOut, ReceiveRequest
from ..services import orders as svc
from ..services import receiving
from .common import respond

router = APIRouter(tags=["purchase orders"])
order = requires("purchasing.order")
# Receivers open the PO they receive (without prices).
view = requires_any("purchasing.order", "purchasing.receive")
COST_NOTE = "Prices (unit_cost, line_total, total) only for users with purchasing.order / purchasing.pay / finance.cost_profit."


@router.get("/purchase-orders", response_model=POPage, description=COST_NOTE)
async def list_orders(
    branch_id: UUID | None = None,
    supplier_id: UUID | None = None,
    status: str | None = Query(default=None, pattern="^(draft|sent|partially_received|received|cancelled)$"),
    q: str | None = Query(default=None, max_length=40, description="PO number"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    items, total = await svc.list_orders(
        session, user, svc.POFilter(branch_id, supplier_id, status, q), page, size
    )
    return respond(
        POPage(items=[POOut.model_validate(p) for p in items], total=total, page=page, size=size), user
    )


@router.post("/purchase-orders", response_model=POOut, status_code=201)
async def create_order(
    body: POCreate, user: CurrentUser = Depends(order), session: AsyncSession = Depends(db.session)
) -> JSONResponse:
    """A draft PO numbered PP1-PO-2026-000001 (per branch and year)."""
    po = await svc.create_order(session, user, body.model_dump())
    return respond(POOut.model_validate(po), user, 201)


@router.get("/purchase-orders/{po_id}", response_model=POOut, description=COST_NOTE)
async def get_order(
    po_id: UUID, user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
) -> JSONResponse:
    return respond(POOut.model_validate(await svc.get_order(session, user, po_id)), user)


@router.patch("/purchase-orders/{po_id}", response_model=POOut)
async def update_order(
    po_id: UUID,
    body: POUpdate,
    user: CurrentUser = Depends(order),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """Draft only."""
    po = await svc.update_order(session, user, po_id, body.model_dump(exclude_unset=True))
    return respond(POOut.model_validate(po), user)


@router.post("/purchase-orders/{po_id}/send", response_model=POOut)
async def send_order(
    po_id: UUID, user: CurrentUser = Depends(order), session: AsyncSession = Depends(db.session)
) -> JSONResponse:
    """Marks the PO as sent to the supplier; lines are fixed from now on."""
    return respond(POOut.model_validate(await svc.send_order(session, user, po_id)), user)


@router.post("/purchase-orders/{po_id}/cancel", response_model=POOut)
async def cancel_order(
    po_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(order),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """Only while nothing was received."""
    return respond(POOut.model_validate(await svc.cancel_order(session, user, po_id, body.reason)), user)


@router.post("/purchase-orders/{po_id}/receive", response_model=ReceiptOut, status_code=201)
async def receive(
    po_id: UUID,
    body: ReceiveRequest,
    _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("purchasing.receive")),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """Receive goods with lot and expiry per line (two lots of one item = two
    lines). Creates the supplier's bill; stock reaches inventory as goods.received.
    Past expiry → BATCH_EXPIRED; within 180 days → short_expiry: true."""
    receipt = await receiving.receive(session, user, po_id, body.model_dump())
    return respond(ReceiptOut.model_validate(receipt), user, 201)
