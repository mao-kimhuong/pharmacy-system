from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.visibility import drop_fields
from pharmacy_shared.xlsx import MAX_FILE_BYTES, XLSX_MEDIA_TYPE

from ..db import db
from ..models import InitializeLock
from ..schemas.inventory import (
    BatchPage,
    LockOut,
    MovementOut,
    MovementPage,
    OpeningOut,
    OpeningPage,
    OpeningRequest,
    QuarantineRelease,
    QuarantineReleaseOut,
    ReasonRequest,
    StockInOut,
    StockInRequest,
    StockPage,
)
from ..services import opening, reservations, stock_in, views
from ..services.common import COST_FIELDS, can_see_cost

router = APIRouter()
view = requires("inventory.view")
initialize = requires("inventory.initialize")
COST_NOTE = "cost_per_base, value and stock_value only for users with finance.cost_profit."


def respond(model: BaseModel | dict[str, Any], user: CurrentUser, status_code: int = 200) -> JSONResponse:
    data = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    if not can_see_cost(user):
        data = drop_fields(data, COST_FIELDS)
    return JSONResponse(data, status_code=status_code)


@router.get("/stock", response_model=StockPage, tags=["stock"], description=COST_NOTE)
async def get_stock(
    branch_id: UUID | None = Query(default=None, description="Left out: all your branches"),
    medicine_id: UUID | None = None,
    q: str | None = Query(default=None, max_length=100, description="SKU or name"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """Stock per branch and medicine, in base units and in pack units, with the
    batches in FEFO order (earliest expiry first)."""
    items, total = await views.stock(session, user, views.StockFilter(branch_id, medicine_id, q), page, size)
    return respond(StockPage(items=items, total=total, page=page, size=size), user)


@router.get("/batches", response_model=BatchPage, tags=["stock"], description=COST_NOTE)
async def get_batches(
    branch_id: UUID | None = None,
    medicine_id: UUID | None = None,
    expiring_within: int | None = Query(default=None, ge=0, le=3650, description="days, e.g. 90"),
    status: str | None = Query(default=None, pattern="^(active|expired|blocked|recalled|quarantine)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """Batches with stock, earliest expiry first (near-expiry list)."""
    items, total = await views.batches(
        session, user, branch_id, medicine_id, expiring_within, status, page, size
    )
    return respond(BatchPage(items=items, total=total, page=page, size=size), user)


@router.get("/movements", response_model=MovementPage, tags=["stock"])
async def get_movements(
    branch_id: UUID | None = None,
    batch_id: UUID | None = None,
    medicine_id: UUID | None = None,
    type: str | None = Query(default=None, max_length=20),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=100),
    user: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> MovementPage:
    items, total = await views.movements(
        session, user, branch_id, batch_id, medicine_id, type, date_from, date_to, page, size
    )
    return MovementPage(
        items=[MovementOut.model_validate(m) for m in items], total=total, page=page, size=size
    )


@router.post("/stock-in", response_model=StockInOut, status_code=201, tags=["stock-in"])
async def quick_stock_in(
    body: StockInRequest,
    _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("inventory.stock_in")),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """Goods without a purchase order (reason required). Past expiry →
    BATCH_EXPIRED; within 180 days → short_expiry: true."""
    result = await stock_in.stock_in(session, user, body.model_dump())
    return respond(StockInOut.model_validate(result), user, 201)


# ---------------------------------------------------------------- initialize


def _opening(ob, user: CurrentUser) -> JSONResponse:  # noqa: ANN001
    return respond(OpeningOut.model_validate(ob), user)


@router.get("/opening-balances/template.xlsx", response_class=Response, tags=["initialize"])
async def opening_template(_: CurrentUser = Depends(initialize)) -> Response:
    return Response(opening.template(), media_type=XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": 'attachment; filename="opening-stock-template.xlsx"'})  # fmt: skip


@router.post("/opening-balances", response_model=OpeningOut, status_code=201, tags=["initialize"])
async def create_opening(
    body: OpeningRequest, user: CurrentUser = Depends(initialize), session: AsyncSession = Depends(db.session)
) -> JSONResponse:
    """Validates the lines only; nothing reaches stock until commit."""
    ob = await opening.create_from_lines(session, user, body.model_dump())
    return respond(OpeningOut.model_validate(ob), user, 201)


@router.post("/opening-balances/upload", response_model=OpeningOut, status_code=201, tags=["initialize"])
async def upload_opening(
    branch_id: UUID = Form(),
    file: UploadFile = File(description=".xlsx: sku, pack_unit, lot_no, expiry_date, qty, unit_cost_usd"),
    user: CurrentUser = Depends(initialize),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise AppError(ErrorCode.FILE_REJECTED, "The file is larger than 10 MB", status_code=422)
    ob = await opening.create_from_xlsx(session, user, branch_id, file.filename or "opening.xlsx", data)
    return respond(OpeningOut.model_validate(ob), user, 201)


@router.get("/opening-balances", response_model=OpeningPage, tags=["initialize"])
async def list_openings(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(initialize),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    items, total = await opening.list_openings(session, user, page, size)
    return respond(OpeningPage(items=[OpeningOut.model_validate(o) for o in items], total=total, page=page,
                               size=size), user)  # fmt: skip


@router.get("/opening-balances/{opening_id}", response_model=OpeningOut, tags=["initialize"])
async def get_opening(
    opening_id: UUID, user: CurrentUser = Depends(initialize), session: AsyncSession = Depends(db.session)
) -> JSONResponse:
    """The lines with their errors."""
    return _opening(await opening.get_opening(session, user, opening_id), user)


@router.post("/opening-balances/{opening_id}/commit", response_model=OpeningOut, tags=["initialize"])
async def commit_opening(
    opening_id: UUID,
    _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(initialize),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """Books every line as opening stock in one transaction and locks the branch."""
    return _opening(await opening.commit_opening(session, user, opening_id), user)


@router.get("/initialize-locks", response_model=list[LockOut], tags=["initialize"])
async def list_locks(
    user: CurrentUser = Depends(initialize), session: AsyncSession = Depends(db.session)
) -> list[InitializeLock]:
    return await opening.locks(session, user)


@router.post("/initialize-locks/{branch_id}/unlock", response_model=LockOut, tags=["initialize"])
async def unlock(
    branch_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(initialize),
    session: AsyncSession = Depends(db.session),
) -> InitializeLock:  # fmt: skip
    """Owner only; logged with the reason."""
    return await opening.unlock(session, user, branch_id, body.reason)


@router.post("/quarantine/release", response_model=QuarantineReleaseOut, tags=["stock"])
async def release_quarantine(
    body: QuarantineRelease,
    user: CurrentUser = Depends(requires("inventory.adjust")),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """A pharmacist puts returned (quarantined) goods back on sale; reason required, logged."""
    return await reservations.release_quarantine(session, user, body.model_dump())
