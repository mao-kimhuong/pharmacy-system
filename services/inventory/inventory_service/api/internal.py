"""/internal/v1 – called by the sales service (sale saga), never through Traefik."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.inventory import (
    ReleaseByRef,
    ReservationOut,
    ReserveRequest,
    ReturnBooked,
    ReturnRequest,
    ReverseRequest,
)
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
