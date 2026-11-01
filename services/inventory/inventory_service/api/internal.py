"""/internal/v1 – called by the sales service (sale saga), never through Traefik."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.inventory import (
    AvailableRequest,
    ControlledMovement,
    ControlledStockRequest,
    FromPurchaseRequest,
    MergeBackRequest,
    MovementsSince,
    PlanOut,
    PlanRequest,
    ReleaseByRef,
    ReservationOut,
    ReserveRequest,
    ReturnBooked,
    ReturnRequest,
    ReverseRequest,
    SnapshotRequest,
    SplitRequest,
    SupplierReturnMove,
    SupplierReturnMoved,
)
from ..services import counting, recalls, transfers
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


@router.post("/reservations/plan", response_model=PlanOut)
async def plan(
    body: PlanRequest,
    caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """The cart preview: the same FEFO allocation and errors as /reservations, no locks, nothing saved."""
    return await svc.reserve(session, caller, body.model_dump(), write=False)


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


# ---------------------------------------------------------------- sales extras (S7)


@router.post("/reservations/{reservation_id}/split", response_model=ReservationOut)
async def split(
    reservation_id: UUID, body: SplitRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Part of a sale order's reservation becomes an invoice's (same batches). Once per invoice."""
    return await svc.split(session, caller, reservation_id, body.model_dump())


@router.post("/reservations/{reservation_id}/merge-back", response_model=ReservationOut | None)
async def merge_back(
    reservation_id: UUID, body: MergeBackRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict | None:  # fmt: skip
    """A failed sale from an order: its invoice reservation goes back onto the order's. Once per invoice."""
    return await svc.merge_back(session, caller, reservation_id, body.ref_id)


@router.post("/stock/available")
async def stock_available(
    body: AvailableRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Sellable now per item (hampers: whole hampers), nothing reserved (resuming a cart)."""
    return {"items": await svc.availability(session, body.branch_id, [i.model_dump() for i in body.items])}


@router.post("/movements/supplier-return", response_model=SupplierReturnMoved)
async def supplier_return(
    body: SupplierReturnMove, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Purchasing submits a supplier return: one supplier_return movement per line, once."""
    return await recalls.supplier_return_movement(session, caller, body.model_dump())
