from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires

from ..db import db
from ..models import Medicine, PackUnit
from ..schemas.catalog import (
    MedicineCreate,
    MedicineOut,
    MedicinePage,
    MedicineUpdate,
    PackUnitCreate,
    PackUnitOut,
    PackUnitUpdate,
    PriceChange,
    ReasonRequest,
    SearchHit,
    SearchPage,
)
from ..services import exports, prices
from ..services import medicines as svc

router = APIRouter(tags=["medicines"])
view = requires("products.view")
manage = requires("products.manage")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/medicines", response_model=MedicinePage)
async def list_medicines(
    q: str | None = Query(default=None, max_length=100, description="name, generic, Khmer name or SKU"),
    category_id: UUID | None = None,
    brand_id: UUID | None = None,
    is_rx_only: bool | None = None,
    controlled: bool | None = None,
    include_inactive: bool = False,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> MedicinePage:
    f = svc.MedicineFilter(q, category_id, brand_id, is_rx_only, controlled, include_inactive)
    items, total = await svc.list_medicines(session, f, page, size)
    return MedicinePage(
        items=[MedicineOut.model_validate(m) for m in items], total=total, page=page, size=size
    )


@router.get("/medicines/search", response_model=SearchPage)
async def search_medicines(
    q: str = Query(min_length=1, max_length=100, description="barcode, SKU, or brand / generic / Khmer name"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> SearchPage:
    """Active products: exact barcode match first (with the scanned pack unit),
    then exact SKU, then names, most similar first."""
    hits, total = await svc.search(session, q, page, size)
    items = [
        SearchHit.model_validate(
            MedicineOut.model_validate(m).model_dump() | {"matched_pack_unit_id": pack_id}
        )
        for m, pack_id in hits
    ]
    return SearchPage(items=items, total=total, page=page, size=size)


@router.get("/medicines/export.xlsx", response_class=Response, responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}, "description": "The .xlsx file"}})  # fmt: skip
async def export_medicines(
    include_inactive: bool = False,
    _: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> Response:
    """All products in the import layout (one row per pack unit)."""
    content = await exports.export_products(session, include_inactive)
    return Response(
        content, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="products.xlsx"'}
    )


@router.post("/medicines", response_model=MedicineOut, status_code=201)
async def create_medicine(
    body: MedicineCreate, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
) -> Medicine:
    """Creates the base pack unit (qty_in_base 1) from base_unit + base_price,
    plus any bigger pack units given."""
    return await svc.create_medicine(session, user, body.model_dump())


@router.get("/medicines/{medicine_id}", response_model=MedicineOut)
async def get_medicine(
    medicine_id: UUID, _: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
) -> Medicine:
    return await svc.get_medicine(session, medicine_id)


@router.patch("/medicines/{medicine_id}", response_model=MedicineOut)
async def update_medicine(
    medicine_id: UUID,
    body: MedicineUpdate,
    user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> Medicine:
    return await svc.update_medicine(session, user, medicine_id, body.model_dump(exclude_unset=True))


@router.get("/medicines/{medicine_id}/price-history", response_model=list[PriceChange])
async def price_history(
    medicine_id: UUID, pack_unit_id: UUID | None = None,
    date_from: date | None = Query(default=None, alias="from"), date_to: date | None = Query(default=None, alias="to"),
    _: CurrentUser = Depends(requires("products.view")), session: AsyncSession = Depends(db.session),
) -> list:  # fmt: skip
    """Every sell price change per pack unit (old → new, who, when). Cost is not in the
    catalog: the reports' Cost change report has the receipts' cost."""
    return await prices.history(session, medicine_id, pack_unit_id, date_from, date_to)


@router.post("/medicines/{medicine_id}/deactivate", response_model=MedicineOut)
async def deactivate_medicine(
    medicine_id: UUID,
    body: ReasonRequest,
    user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> Medicine:
    """Can no longer be sold or bought; its history stays."""
    return await svc.set_medicine_active(session, user, medicine_id, False, body.reason)


@router.post("/medicines/{medicine_id}/activate", response_model=MedicineOut)
async def activate_medicine(
    medicine_id: UUID, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
) -> Medicine:
    return await svc.set_medicine_active(session, user, medicine_id, True, None)


@router.get("/medicines/{medicine_id}/pack-units", response_model=list[PackUnitOut])
async def list_pack_units(
    medicine_id: UUID, _: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
) -> list[PackUnit]:
    return list((await svc.get_medicine(session, medicine_id)).pack_units)


@router.post("/medicines/{medicine_id}/pack-units", response_model=PackUnitOut, status_code=201)
async def add_pack_unit(
    medicine_id: UUID,
    body: PackUnitCreate,
    user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> PackUnit:
    return await svc.add_pack_unit(session, user, medicine_id, body.model_dump())


@router.patch("/pack-units/{pack_unit_id}", response_model=PackUnitOut)
async def update_pack_unit(
    pack_unit_id: UUID,
    body: PackUnitUpdate,
    user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> PackUnit:
    return await svc.update_pack_unit(session, user, pack_unit_id, body.model_dump(exclude_unset=True))


@router.post("/pack-units/{pack_unit_id}/deactivate", response_model=PackUnitOut)
async def deactivate_pack_unit(
    pack_unit_id: UUID,
    body: ReasonRequest,
    user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> PackUnit:
    return await svc.set_pack_unit_active(session, user, pack_unit_id, False, body.reason)


@router.post("/pack-units/{pack_unit_id}/activate", response_model=PackUnitOut)
async def activate_pack_unit(
    pack_unit_id: UUID, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
) -> PackUnit:
    return await svc.set_pack_unit_active(session, user, pack_unit_id, True, None)
