from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.storage import Storage
from pharmacy_shared.uploads import MAX_BYTES

from ..db import db
from ..models import Shrinkage
from ..schemas.inventory import (
    LocationIn,
    LocationOut,
    LocationRow,
    ReasonRequest,
    ShrinkageIn,
    ShrinkageOut,
    ShrinkagePage,
)
from ..services import locations, shrinkage
from ..services.clients import get_auth, get_storage
from .inventory import respond

router = APIRouter()
see_shrinkage = requires_any("inventory.shrinkage", "inventory.shrinkage_approve")
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}


def _out(s: Shrinkage) -> ShrinkageOut:
    out = ShrinkageOut.model_validate(s)
    out.lot_no, out.has_photo = s.batch.lot_no, bool(s.photo_key)
    return out


@router.put("/shelf-locations", response_model=LocationOut, tags=["shelf locations"])
async def set_location(
    body: LocationIn, user: CurrentUser = Depends(requires("inventory.locations")),
    session: AsyncSession = Depends(db.session),
) -> object:  # fmt: skip
    """Where the medicine sits at the branch ("A3"); empty code clears it. Logged."""
    return await locations.set_location(session, user, body.model_dump())


@router.get("/shelf-locations", response_model=list[LocationRow], tags=["shelf locations"])
async def list_locations(
    branch_id: UUID, code: str | None = Query(default=None, max_length=12),
    user: CurrentUser = Depends(requires("inventory.view")), session: AsyncSession = Depends(db.session),
) -> list[dict]:  # fmt: skip
    return await locations.list_locations(session, user, branch_id, code)


@router.post("/shrinkages", response_model=ShrinkageOut, status_code=201, tags=["shrinkage"])
async def create_shrinkage(
    body: ShrinkageIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("inventory.shrinkage")), session: AsyncSession = Depends(db.session),
    auth: InternalClient = Depends(get_auth),
) -> JSONResponse:  # fmt: skip
    """Write off stock. Controlled: your PIN + a witness's PIN and the destruction method.
    Above the branch limit (50 USD): pending until a manager approves."""
    s = await shrinkage.create(session, user, auth, body.model_dump())
    return respond(_out(s), user, 201)


@router.get("/shrinkages", response_model=ShrinkagePage, tags=["shrinkage"])
async def list_shrinkages(
    branch_id: UUID | None = None, status: str | None = Query(default=None, max_length=20),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(see_shrinkage), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    items, total = await shrinkage.list_shrinkages(session, user, shrinkage.ShrinkageFilter(branch_id, status),
                                                   page, size)  # fmt: skip
    return respond(ShrinkagePage(items=[_out(s) for s in items], total=total, page=page, size=size), user)


@router.post("/shrinkages/{shrinkage_id}/approve", response_model=ShrinkageOut, tags=["shrinkage"])
async def approve_shrinkage(
    shrinkage_id: UUID, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("inventory.shrinkage_approve")), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    return respond(_out(await shrinkage.approve(session, user, shrinkage_id)), user)


@router.post("/shrinkages/{shrinkage_id}/reject", response_model=ShrinkageOut, tags=["shrinkage"])
async def reject_shrinkage(
    shrinkage_id: UUID, body: ReasonRequest,
    user: CurrentUser = Depends(requires("inventory.shrinkage_approve")), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    return respond(_out(await shrinkage.reject(session, user, shrinkage_id, body.reason)), user)


@router.post("/shrinkages/{shrinkage_id}/photo", response_model=ShrinkageOut, tags=["shrinkage"])
async def add_photo(
    shrinkage_id: UUID, file: UploadFile = File(description="JPEG, PNG or PDF, at most 10 MB"),
    user: CurrentUser = Depends(requires("inventory.shrinkage")), session: AsyncSession = Depends(db.session),
    storage: Storage = Depends(get_storage),
) -> JSONResponse:  # fmt: skip
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise AppError(ErrorCode.FILE_REJECTED, "The file is larger than 10 MB", status_code=413)
    return respond(_out(await shrinkage.add_photo(session, user, storage, shrinkage_id, data)), user)


@router.get("/shrinkages/{shrinkage_id}/photo", response_class=Response, tags=["shrinkage"],
            responses={200: {"content": {t: {} for t in EXTENSIONS}}})  # fmt: skip
async def read_photo(
    shrinkage_id: UUID, user: CurrentUser = Depends(see_shrinkage), session: AsyncSession = Depends(db.session),
    storage: Storage = Depends(get_storage),
) -> Response:  # fmt: skip
    """Streamed through this service (user, branch, permission checked; logged each time)."""
    s, data = await shrinkage.read_photo(session, user, storage, shrinkage_id)
    return Response(content=data, media_type=s.photo_type, headers={
        "Content-Disposition": f'inline; filename="{s.number}.{EXTENSIONS.get(s.photo_type, "bin")}"',
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })  # fmt: skip
