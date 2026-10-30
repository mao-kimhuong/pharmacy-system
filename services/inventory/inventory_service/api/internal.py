"""/internal/v1 – called by the sales service (sale saga), never through Traefik."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.inventory import (
    ControlledMovement,
    ControlledStockRequest,
    FromPurchaseRequest,
    MovementsSince,
    ReleaseByRef,
    ReservationOut,
    ReserveRequest,
    ReturnBooked,
    ReturnRequest,
    ReverseRequest,
    SnapshotRequest,
)
from ..services import counting, transfers
from ..services import reservations as svc

router = APIRouter()


@router.post("/reservations", response_model=ReservationOut)
async def reserve(
    body: ReserveRequest,
    caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """FEFO, split over batches, row-locked; once per invoice. OUT_OF_STOCK lists the short lines."""
    return await svc.reserve(session, caller, body.model_dump())


@router.post("/reservations/release-by-ref", response_model=ReservationOut | None)
async def release_by_ref(
    body: ReleaseByRef,
    caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict | None:
    return await svc.release_by_ref(session, caller, body.ref_type, body.ref_id)


@router.post("/reservations/{reservation_id}/confirm", response_model=ReservationOut)
async def confirm(
    reservation_id: UUID, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """The goods are sold: "out" movements."""
    return await svc.confirm(session, caller, reservation_id)


@router.post("/reservations/{reservation_id}/release", response_model=ReservationOut)
async def release(
    reservation_id: UUID, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    return await svc.release(session, caller, reservation_id)


@router.post("/reservations/{reservation_id}/reverse", response_model=ReservationOut)
async def reverse(
    reservation_id: UUID, body: ReverseRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """A cancelled sale: the stock goes back into the same batches."""
    return await svc.reverse(session, caller, reservation_id, body.reason)


@router.post("/returns", response_model=list[ReturnBooked])
async def returns(
    body: ReturnRequest,
    caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> list[dict]:
    """Returned goods back into their batch, or into quarantine."""
    return await svc.book_returns(session, caller, body.model_dump())


# ---------------------------------------------------------------- stock take, controlled register (S5)


@router.post("/stock/snapshot")
async def stock_snapshot(
    body: SnapshotRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Stock per batch for a stock take, valid at `as_of_seq` (no quantities are shown to counters)."""
    return await counting.snapshot(session, body.model_dump())


@router.post("/movements/since")
async def movements_since(
    body: MovementsSince, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    return await counting.movements_since(session, body.model_dump())


@router.post("/stock/controlled")
async def controlled_stock(
    body: ControlledStockRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    return await counting.controlled_stock(session, body.model_dump())


@router.post("/movements/controlled")
async def controlled_movement(
    body: ControlledMovement, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Adjust or destroy controlled stock (PIN + witness checked by the controlled service); once per request_id."""
    return await counting.controlled_movement(session, caller, body.model_dump())


# ---------------------------------------------------------------- purchasing (S6)


@router.post("/transfers/from-purchase-request")
async def transfer_from_purchase_request(
    body: FromPurchaseRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """A purchase request filled from another branch: approved request + transfer, once per source_ref."""
    return await transfers.from_purchase_request(session, caller, body.model_dump())
