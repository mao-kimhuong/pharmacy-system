from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any

from ..db import db
from ..models import Medicine, Promotion
from ..schemas.catalog import (
    HamperComponentsIn,
    HamperCreate,
    MedicineOut,
    PromotionCreate,
    PromotionOut,
    PromotionUpdate,
)
from ..services import hampers, promotions

router = APIRouter()
hamper_perm = requires("catalog.hampers")
promo_perm = requires("catalog.promotions")


def _dump(model: object) -> dict:
    return model.model_dump(mode="json")  # type: ignore[attr-defined]


@router.post("/hampers", response_model=MedicineOut, status_code=201, tags=["hampers"])
async def create_hamper(
    body: HamperCreate, user: CurrentUser = Depends(hamper_perm), session: AsyncSession = Depends(db.session),
) -> Medicine:  # fmt: skip
    """A kit sold as one item (own price and barcode) made of other medicines; no stock of its own.
    Rx-only when a component is."""
    return await hampers.create_hamper(session, user, body.model_dump())


@router.get("/hampers", response_model=list[MedicineOut], tags=["hampers"])
async def list_hampers(
    _: CurrentUser = Depends(requires_any("catalog.hampers", "products.view")),
    session: AsyncSession = Depends(db.session),
) -> list[Medicine]:  # fmt: skip
    return await hampers.list_hampers(session)


@router.put("/hampers/{hamper_id}/components", response_model=MedicineOut, tags=["hampers"])
async def set_components(
    hamper_id: UUID, body: HamperComponentsIn, user: CurrentUser = Depends(hamper_perm),
    session: AsyncSession = Depends(db.session),
) -> Medicine:  # fmt: skip
    return await hampers.set_components(session, user, hamper_id, body.model_dump()["components"])


@router.post("/promotions", response_model=PromotionOut, status_code=201, tags=["promotions"])
async def create_promotion(
    body: PromotionCreate, user: CurrentUser = Depends(promo_perm), session: AsyncSession = Depends(db.session),
) -> Promotion:  # fmt: skip
    return await promotions.create(session, user, body.model_dump(mode="json") | _times(body))


def _times(body: PromotionCreate | PromotionUpdate) -> dict:
    """Keep date-times and numbers as Python values (JSON mode turns them into strings)."""
    raw = body.model_dump(exclude_unset=True)
    return {k: raw[k] for k in ("starts_at", "ends_at", "value") if k in raw}


@router.get("/promotions", response_model=list[PromotionOut], tags=["promotions"])
async def list_promotions(
    active: bool | None = None, _: CurrentUser = Depends(requires_any("catalog.promotions", "pos.sell")),
    session: AsyncSession = Depends(db.session),
) -> list[Promotion]:  # fmt: skip
    return await promotions.list_promotions(session, active)


@router.patch("/promotions/{promotion_id}", response_model=PromotionOut, tags=["promotions"])
async def update_promotion(
    promotion_id: UUID, body: PromotionUpdate, user: CurrentUser = Depends(promo_perm),
    session: AsyncSession = Depends(db.session),
) -> Promotion:  # fmt: skip
    data = body.model_dump(mode="json", exclude_unset=True) | _times(body)
    return await promotions.update(session, user, promotion_id, data)


@router.post("/promotions/{promotion_id}/deactivate", response_model=PromotionOut, tags=["promotions"])
async def deactivate(
    promotion_id: UUID, user: CurrentUser = Depends(promo_perm), session: AsyncSession = Depends(db.session),
) -> Promotion:  # fmt: skip
    return await promotions.set_active(session, user, promotion_id, False)


@router.post("/promotions/{promotion_id}/activate", response_model=PromotionOut, tags=["promotions"])
async def activate(
    promotion_id: UUID, user: CurrentUser = Depends(promo_perm), session: AsyncSession = Depends(db.session),
) -> Promotion:  # fmt: skip
    return await promotions.set_active(session, user, promotion_id, True)
