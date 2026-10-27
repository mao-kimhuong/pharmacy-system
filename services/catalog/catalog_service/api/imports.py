from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..models import ProductImport
from ..schemas.imports import ImportCommit, ImportDetail, ImportPage, ImportRowOut, ImportSummary
from ..services import imports as svc
from ..services import spreadsheet
from .medicines import XLSX

router = APIRouter(tags=["imports"])
can_import = requires("products.import")


@router.get("/imports/template.xlsx", response_class=Response)
async def import_template(_: CurrentUser = Depends(can_import)) -> Response:
    return Response(
        spreadsheet.template(),
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="products-template.xlsx"'},
    )


@router.post("/imports", response_model=ImportSummary, status_code=201)
async def upload_import(
    file: UploadFile = File(description=".xlsx, at most 10 MB"),
    user: CurrentUser = Depends(can_import),
    session: AsyncSession = Depends(db.session),
) -> ProductImport:
    """Reads and validates every row. Nothing is saved to the products yet:
    see GET /imports/{id} for row errors, then POST /imports/{id}/commit."""
    data = await file.read(spreadsheet.MAX_FILE_BYTES + 1)
    if len(data) > spreadsheet.MAX_FILE_BYTES:
        raise AppError(ErrorCode.FILE_REJECTED, "The file is larger than 10 MB", status_code=422)
    return await svc.create_import(session, user, file.filename or "import.xlsx", data)


@router.get("/imports", response_model=ImportPage)
async def list_imports(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _: CurrentUser = Depends(can_import),
    session: AsyncSession = Depends(db.session),
) -> ImportPage:
    items, total = await svc.list_imports(session, page, size)
    return ImportPage(
        items=[ImportSummary.model_validate(i) for i in items], total=total, page=page, size=size
    )


@router.get("/imports/{import_id}", response_model=ImportDetail)
async def get_import(
    import_id: UUID,
    errors_only: bool = False,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=100, ge=1, le=500),
    _: CurrentUser = Depends(can_import),
    session: AsyncSession = Depends(db.session),
) -> ImportDetail:
    """The import with its rows (paged) and each row's errors."""
    imp = await svc.get_import(session, import_id)
    rows, total = await svc.list_rows(session, imp.id, errors_only, page, size)
    return ImportDetail(
        **ImportSummary.model_validate(imp).model_dump(),
        rows=[ImportRowOut.model_validate(r) for r in rows],
        rows_total=total,
        page=page,
        size=size,
    )


@router.post("/imports/{import_id}/commit", response_model=ImportSummary)
async def commit_import(
    import_id: UUID,
    body: ImportCommit,
    _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(can_import),
    session: AsyncSession = Depends(db.session),
) -> ProductImport:
    """Creates or updates every product by SKU in one transaction. Refused
    (IMPORT_HAS_ERRORS) while rows have errors, unless skip_invalid=true."""
    return await svc.commit_import(
        session, user, import_id, create_missing=body.create_missing, skip_invalid=body.skip_invalid
    )
