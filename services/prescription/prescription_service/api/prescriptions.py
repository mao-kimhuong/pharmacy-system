from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.storage import Storage
from pharmacy_shared.uploads import MAX_BYTES

from ..db import db
from ..models import Prescription, RxAttachment
from ..schemas.rx import AttachmentOut, ReasonRequest, Remaining, RxCreate, RxOut, RxPage, RxUpdate, Status
from ..services import attachments, prescriptions
from ..services.prescriptions import RxFilter
from .storage import get_storage

router = APIRouter(tags=["prescriptions"])
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}


@router.get("/prescriptions", response_model=RxPage)
async def list_prescriptions(
    patient_id: UUID | None = None, status: Status | None = None,
    q: str | None = Query(default=None, max_length=40, description="Prescription number"),
    page: int = Query(default=1, ge=1), size: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(requires("prescriptions.view")), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    items, total = await prescriptions.list_rx(session, user, RxFilter(patient_id, status, q), page, size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("/prescriptions", response_model=RxOut, status_code=201)
async def create_prescription(
    body: RxCreate, user: CurrentUser = Depends(requires("prescriptions.manage")),
    session: AsyncSession = Depends(db.session),
) -> Prescription:  # fmt: skip
    """A draft. Upload the photo with POST /prescriptions/{id}/attachments, then activate."""
    return await prescriptions.create_rx(session, user, body.model_dump())


@router.get("/prescriptions/{rx_id}", response_model=RxOut)
async def get_prescription(
    rx_id: UUID, user: CurrentUser = Depends(requires("prescriptions.view")),
    session: AsyncSession = Depends(db.session),
) -> Prescription:  # fmt: skip
    return await prescriptions.get_rx(session, user, rx_id)


@router.patch("/prescriptions/{rx_id}", response_model=RxOut)
async def update_prescription(
    rx_id: UUID, body: RxUpdate, user: CurrentUser = Depends(requires("prescriptions.manage")),
    session: AsyncSession = Depends(db.session),
) -> Prescription:  # fmt: skip
    """Draft only."""
    return await prescriptions.update_rx(session, user, rx_id, body.model_dump(exclude_unset=True))


@router.post("/prescriptions/{rx_id}/activate", response_model=RxOut)
async def activate_prescription(
    rx_id: UUID, user: CurrentUser = Depends(requires("prescriptions.manage")),
    session: AsyncSession = Depends(db.session),
) -> Prescription:  # fmt: skip
    return await prescriptions.activate(session, user, rx_id)


@router.post("/prescriptions/{rx_id}/cancel", response_model=RxOut)
async def cancel_prescription(
    rx_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(requires("prescriptions.manage")),
    session: AsyncSession = Depends(db.session),
) -> Prescription:  # fmt: skip
    """With a reason; never deleted. Not while a sale is holding quantity."""
    return await prescriptions.cancel(session, user, rx_id, body.reason)


@router.get("/prescriptions/{rx_id}/remaining", response_model=Remaining)
async def remaining(
    rx_id: UUID, user: CurrentUser = Depends(requires("prescriptions.view")),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """What can still be dispensed per item; the POS calls this before adding Rx lines."""
    return await prescriptions.remaining(session, user, rx_id)


@router.post("/prescriptions/{rx_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    rx_id: UUID, file: UploadFile = File(description="JPEG, PNG or PDF, at most 10 MB"),
    user: CurrentUser = Depends(requires("prescriptions.manage")), session: AsyncSession = Depends(db.session),
    storage: Storage = Depends(get_storage),
) -> RxAttachment:  # fmt: skip
    """Checked by content (not by name); photos lose their EXIF data; PDFs with
    scripts, launch actions or embedded files are refused."""
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise AppError(ErrorCode.FILE_REJECTED, "The file is larger than 10 MB", status_code=413,
                       details={"max_bytes": MAX_BYTES})  # fmt: skip
    return await attachments.upload(session, user, storage, rx_id, file.filename or "", data)


@router.get("/prescriptions/{rx_id}/attachments/{attachment_id}", response_class=Response,
            responses={200: {"content": {t: {} for t in EXTENSIONS}}})  # fmt: skip
async def download_attachment(
    rx_id: UUID, attachment_id: UUID, user: CurrentUser = Depends(requires("prescriptions.view")),
    session: AsyncSession = Depends(db.session), storage: Storage = Depends(get_storage),
) -> Response:  # fmt: skip
    """Streamed through this service: user, branch and permission checked on every
    request, and every view is written to the User Log. Never cached."""
    att, data = await attachments.download(session, user, storage, rx_id, attachment_id)
    name = attachments.safe_filename(att.original_filename, EXTENSIONS.get(att.content_type, "bin"))
    return Response(content=data, media_type=att.content_type, headers={
        "Content-Disposition": attachments.content_disposition(name),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
    })  # fmt: skip
