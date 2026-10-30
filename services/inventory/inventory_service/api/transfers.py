from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user, requires_any
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.internal import InternalClient

from ..db import db
from ..models import Transfer, TransferRequest
from ..schemas.inventory import (
    InTransitRow,
    PickIn,
    ReasonRequest,
    ReceiveIn,
    ResolveIn,
    SignoffIn,
    TransferOut,
    TransferPage,
    TransferPushIn,
    TransferRequestIn,
    TransferRequestOut,
)
from ..services import transfers
from ..services.clients import get_auth
from .inventory import respond

router = APIRouter(tags=["transfers"])
see = requires_any("transfers.request", "transfers.approve", "transfers.dispatch", "transfers.receive",
                   "transfers.resolve", "inventory.view")  # fmt: skip


def out(t: Transfer) -> dict[str, Any]:
    transit = transfers.in_transit_of(t)
    data = TransferOut.model_validate(t).model_dump(mode="json")
    for p, row in zip(t.picks, data["picks"], strict=True):
        row.update(lot_no=p.batch.lot_no, expiry_date=p.batch.expiry_date.isoformat(), in_transit=transit.get(p.id, 0),
                   cost_per_base=str(p.batch.cost_per_base))  # fmt: skip
    return data


@router.post("/transfer-requests", response_model=TransferRequestOut, status_code=201)
async def create_request(
    body: TransferRequestIn, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session),
) -> TransferRequest:  # fmt: skip
    """Ask another branch for stock (transfers.request at your branch, the destination)."""
    r = await transfers.create_request(session, user, body.model_dump())
    await session.commit()
    return r


@router.get("/transfer-requests", response_model=list[TransferRequestOut])
async def list_requests(
    branch_id: UUID | None = None, status: str | None = Query(default=None, max_length=10),
    user: CurrentUser = Depends(see), session: AsyncSession = Depends(db.session),
) -> list[TransferRequest]:  # fmt: skip
    return await transfers.list_requests(session, user, branch_id, status)


@router.post("/transfer-requests/{request_id}/approve", response_model=TransferOut)
async def approve_request(
    request_id: UUID, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """The source branch agrees (transfers.approve): the transfer is made, ready to pick."""
    return respond(out(await transfers.approve_request(session, user, request_id)), user, 200)


@router.post("/transfer-requests/{request_id}/reject", response_model=TransferRequestOut)
async def reject_request(
    request_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> TransferRequest:  # fmt: skip
    return await transfers.decide_request(session, user, request_id, body.reason, "reject")


@router.post("/transfer-requests/{request_id}/cancel", response_model=TransferRequestOut)
async def cancel_request(
    request_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> TransferRequest:  # fmt: skip
    return await transfers.decide_request(session, user, request_id, body.reason, "cancel")


@router.post("/transfers", response_model=TransferOut, status_code=201)
async def push(
    body: TransferPushIn, user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """The source sends stock without a request (transfers.dispatch at the source)."""
    return respond(out(await transfers.push(session, user, body.model_dump())), user, 201)


@router.get("/transfers", response_model=TransferPage)
async def list_transfers(
    branch_id: UUID | None = None, direction: str | None = Query(default=None, pattern="^(in|out)$"),
    status: str | None = Query(default=None, max_length=12), page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200), user: CurrentUser = Depends(see),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    items, total = await transfers.list_transfers(session, user, transfers.TransferFilter(branch_id, direction, status),
                                                  page, size)  # fmt: skip
    return respond({"items": [out(t) for t in items], "total": total, "page": page, "size": size}, user)


@router.get("/transfers/in-transit", response_model=list[InTransitRow])
async def in_transit(
    branch_id: UUID | None = None, user: CurrentUser = Depends(see), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """Stock between branches (dispatched, not yet received or resolved), both directions."""
    rows = [
        InTransitRow.model_validate(r).model_dump(mode="json")
        for r in await transfers.in_transit(session, user, branch_id)
    ]
    return respond(rows, user)  # type: ignore[arg-type]


@router.get("/transfers/by-number/{number}", response_model=TransferOut)
async def by_number(
    number: str, user: CurrentUser = Depends(see), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """Open a transfer by scanning the QR code on its transfer note."""
    return respond(out(await transfers.by_number(session, user, number)), user)


@router.get("/transfers/{transfer_id}", response_model=TransferOut)
async def get_transfer(
    transfer_id: UUID, user: CurrentUser = Depends(see), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    return respond(out(await transfers.get_transfer(session, user, transfer_id)), user)


@router.post("/transfers/{transfer_id}/pick", response_model=TransferOut)
async def pick(
    transfer_id: UUID, body: PickIn, user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """FEFO unless a line names batches (with a reason). Reserves the stock at the source."""
    return respond(out(await transfers.pick(session, user, transfer_id, body.model_dump())), user)


@router.post("/transfers/{transfer_id}/dispatch", response_model=TransferOut)
async def dispatch(
    transfer_id: UUID, body: SignoffIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session),
    auth: InternalClient = Depends(get_auth),
) -> JSONResponse:  # fmt: skip
    """Out of the source, into transit. Controlled lines: your PIN + a witness's PIN."""
    return respond(out(await transfers.dispatch(session, user, auth, transfer_id, body.model_dump())), user)


@router.post("/transfers/{transfer_id}/receive", response_model=TransferOut)
async def receive(
    transfer_id: UUID, body: ReceiveIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session),
    auth: InternalClient = Depends(get_auth),
) -> JSONResponse:  # fmt: skip
    """Good quantity into stock (same batches); short / damaged / extra open a difference."""
    return respond(out(await transfers.receive(session, user, auth, transfer_id, body.model_dump())), user)


@router.post("/transfers/{transfer_id}/differences/{discrepancy_id}/resolve", response_model=TransferOut)
async def resolve(
    transfer_id: UUID, discrepancy_id: UUID, body: ResolveIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(current_user), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    return respond(
        out(await transfers.resolve(session, user, transfer_id, discrepancy_id, body.model_dump())), user
    )


@router.post("/transfers/{transfer_id}/cancel", response_model=TransferOut)
async def cancel(
    transfer_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """Only before dispatch; the reserved stock is released."""
    return respond(out(await transfers.cancel(session, user, transfer_id, body.reason)), user)
