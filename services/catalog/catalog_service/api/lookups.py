"""Categories and brands: same endpoints for both."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires

from ..db import db
from ..models import Brand, Category
from ..schemas.catalog import LookupCreate, LookupOut, LookupUpdate, ReasonRequest
from ..services import lookups as svc

router = APIRouter()
view = requires("products.view")
manage = requires("products.manage")


def _routes(path: str, model: type, tag: str) -> None:
    @router.get(f"/{path}", response_model=list[LookupOut], tags=[tag], name=f"list_{path}")
    async def list_rows(
        include_inactive: bool = False,
        _: CurrentUser = Depends(view),
        session: AsyncSession = Depends(db.session),
    ):
        return await svc.list_rows(session, model, include_inactive)

    @router.post(f"/{path}", response_model=LookupOut, status_code=201, tags=[tag], name=f"create_{path}")
    async def create_row(
        body: LookupCreate, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
    ):
        return await svc.create_row(session, user, model, body.model_dump())

    @router.get(f"/{path}/{{row_id}}", response_model=LookupOut, tags=[tag], name=f"get_{path}")
    async def get_row(
        row_id: UUID, _: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
    ):
        return await svc.get_row(session, model, row_id)

    @router.patch(f"/{path}/{{row_id}}", response_model=LookupOut, tags=[tag], name=f"update_{path}")
    async def update_row(
        row_id: UUID,
        body: LookupUpdate,
        user: CurrentUser = Depends(manage),
        session: AsyncSession = Depends(db.session),
    ):
        return await svc.update_row(session, user, model, row_id, body.model_dump(exclude_unset=True))

    @router.post(
        f"/{path}/{{row_id}}/deactivate", response_model=LookupOut, tags=[tag], name=f"deactivate_{path}"
    )
    async def deactivate_row(
        row_id: UUID,
        body: ReasonRequest,
        user: CurrentUser = Depends(manage),
        session: AsyncSession = Depends(db.session),
    ):
        """Hidden from pick lists; medicines that use it keep it."""
        return await svc.set_active(session, user, model, row_id, False, body.reason)

    @router.post(
        f"/{path}/{{row_id}}/activate", response_model=LookupOut, tags=[tag], name=f"activate_{path}"
    )
    async def activate_row(
        row_id: UUID, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)
    ):
        return await svc.set_active(session, user, model, row_id, True, None)


_routes("categories", Category, "categories")
_routes("brands", Brand, "brands")
