from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any

from ..db import db
from ..models import Supplier, SupplierGroup
from ..schemas.purchasing import (
    GroupCreate,
    GroupOut,
    GroupUpdate,
    ReasonRequest,
    SupplierCreate,
    SupplierOut,
    SupplierPage,
    SupplierUpdate,
)
from ..services import suppliers as svc

router = APIRouter()
manage = requires("contacts.suppliers")
# Picking a supplier on a PO, a receipt or a payment needs to read them.
view = requires_any("contacts.suppliers", "purchasing.order", "purchasing.receive", "purchasing.pay")


@router.get("/supplier-groups", response_model=list[GroupOut], tags=["supplier groups"])
async def list_groups(
    include_inactive: bool = False,
    _: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> list[SupplierGroup]:
    """Always available; the menu item is hidden while the supplier_groups switch is off."""
    return await svc.list_groups(session, include_inactive)


@router.post("/supplier-groups", response_model=GroupOut, status_code=201, tags=["supplier groups"])
async def create_group(
    body: GroupCreate, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
) -> SupplierGroup:
    return await svc.create_group(session, user, body.model_dump())


@router.patch("/supplier-groups/{group_id}", response_model=GroupOut, tags=["supplier groups"])
async def update_group(
    group_id: UUID, body: GroupUpdate, user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> SupplierGroup:  # fmt: skip
    return await svc.update_group(session, user, group_id, body.model_dump(exclude_unset=True))


@router.post("/supplier-groups/{group_id}/deactivate", response_model=GroupOut, tags=["supplier groups"])
async def deactivate_group(
    group_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> SupplierGroup:  # fmt: skip
    return await svc.set_group_active(session, user, group_id, False, body.reason)


@router.post("/supplier-groups/{group_id}/activate", response_model=GroupOut, tags=["supplier groups"])
async def activate_group(
    group_id: UUID, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
) -> SupplierGroup:
    return await svc.set_group_active(session, user, group_id, True, None)


@router.get("/suppliers", response_model=SupplierPage, tags=["suppliers"])
async def list_suppliers(
    q: str | None = Query(default=None, max_length=100, description="name, code, Khmer name or phone"),
    group_id: UUID | None = None,
    include_inactive: bool = False,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    _: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> SupplierPage:
    items, total = await svc.list_suppliers(session, q, group_id, include_inactive, page, size)
    return SupplierPage(
        items=[SupplierOut.model_validate(s) for s in items], total=total, page=page, size=size
    )


@router.post("/suppliers", response_model=SupplierOut, status_code=201, tags=["suppliers"])
async def create_supplier(
    body: SupplierCreate, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
) -> Supplier:
    return await svc.create_supplier(session, user, body.model_dump())


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut, tags=["suppliers"])
async def get_supplier(
    supplier_id: UUID, _: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
) -> Supplier:
    return await svc.get_supplier(session, supplier_id)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut, tags=["suppliers"])
async def update_supplier(
    supplier_id: UUID, body: SupplierUpdate, user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> Supplier:  # fmt: skip
    return await svc.update_supplier(session, user, supplier_id, body.model_dump(exclude_unset=True))


@router.post("/suppliers/{supplier_id}/deactivate", response_model=SupplierOut, tags=["suppliers"])
async def deactivate_supplier(
    supplier_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(manage),
    session: AsyncSession = Depends(db.session),
) -> Supplier:  # fmt: skip
    """No new POs; its POs, bills and payments stay."""
    return await svc.set_supplier_active(session, user, supplier_id, False, body.reason)


@router.post("/suppliers/{supplier_id}/activate", response_model=SupplierOut, tags=["suppliers"])
async def activate_supplier(
    supplier_id: UUID, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
) -> Supplier:
    return await svc.set_supplier_active(session, user, supplier_id, True, None)
