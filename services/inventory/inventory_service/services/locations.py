"""Shelf locations: a short code per branch + medicine ("A3", "FRIDGE-1").
Managers (inventory.locations) set them for their branches; an empty code
clears it. Logged. Stock takes can be scoped by location."""

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import Product, ShelfLocation
from .common import audit, branch_for

CODE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,11}$")


def normalize(code: str | None) -> str:
    value = (code or "").strip().upper()
    if value and not CODE.match(value):
        raise AppError(ErrorCode.VALIDATION_ERROR, "A location is 1-12 letters, digits or -", status_code=422,
                       details={"field": "code"})  # fmt: skip
    return value


async def set_location(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> ShelfLocation:
    branch = await branch_for(session, actor, data["branch_id"])
    product = await session.get(Product, data["medicine_id"])
    if product is None:
        raise AppError(ErrorCode.UNKNOWN_MEDICINE, "Unknown medicine", status_code=422)
    code = normalize(data.get("code"))
    old = await session.get(ShelfLocation, (branch.id, product.id))
    before = old.code if old else ""
    await session.execute(insert(ShelfLocation).values(
        branch_id=branch.id, medicine_id=product.id, code=code, updated_by=actor.id,
    ).on_conflict_do_update(index_elements=["branch_id", "medicine_id"],
                            set_={"code": code, "updated_by": actor.id}))  # fmt: skip
    if before != code:
        audit(session, actor, "shelf_location.set", "medicine", product.id, branch_id=branch.id,
              before={"location": before}, after={"location": code, "sku": product.sku})  # fmt: skip
    await session.commit()
    return await session.get(ShelfLocation, (branch.id, product.id), populate_existing=True)


async def list_locations(session: AsyncSession, actor: CurrentUser, branch_id: UUID, code: str | None):  # noqa: ANN201
    actor.require_branch(branch_id)
    query = (select(ShelfLocation, Product).join(Product, Product.id == ShelfLocation.medicine_id)
             .where(ShelfLocation.branch_id == branch_id, ShelfLocation.code != ""))  # fmt: skip
    if code:
        query = query.where(ShelfLocation.code == normalize(code))
    rows = await session.execute(query.order_by(ShelfLocation.code, Product.sku))
    return [{"branch_id": loc.branch_id, "medicine_id": loc.medicine_id, "code": loc.code, "sku": p.sku,
             "name": p.display_name} for loc, p in rows]  # fmt: skip
