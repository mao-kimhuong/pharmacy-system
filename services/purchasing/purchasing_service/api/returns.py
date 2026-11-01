"""Supplier returns (S8b): draft, submit (stock out, credit or refund), cancel a draft."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.visibility import drop_fields

from ..db import db
from ..models import SupplierReturn
from ..schemas.purchasing import ReasonRequest, SubmitReturnIn, SupplierReturnIn, SupplierReturnOut
from ..services import supplier_returns as svc
from ..services.clients import get_auth, get_inventory
from ..services.common import can_see_cost

router = APIRouter(tags=["supplier returns"])
perm = requires("purchasing.return")
COST = {"cost_per_base", "line_total", "total"}


def respond(r: SupplierReturn | list[SupplierReturn], user: CurrentUser, status_code: int = 200) -> JSONResponse:
    data = ([SupplierReturnOut.model_validate(x).model_dump(mode="json") for x in r] if isinstance(r, list)
            else SupplierReturnOut.model_validate(r).model_dump(mode="json"))  # fmt: skip
    return JSONResponse(data if can_see_cost(user) else drop_fields(data, COST), status_code=status_code)


@router.post("/supplier-returns", response_model=SupplierReturnOut, status_code=201)
async def create(body: SupplierReturnIn, user: CurrentUser = Depends(perm),
                 session: AsyncSession = Depends(db.session)) -> JSONResponse:  # fmt: skip
    """A draft: batches (lots) and quantities going back to the supplier."""
    return respond(await svc.create(session, user, body.model_dump()), user, 201)


@router.get("/supplier-returns", response_model=list[SupplierReturnOut])
async def list_returns(branch_id: UUID | None = None, status: str | None = None, user: CurrentUser = Depends(perm),
                       session: AsyncSession = Depends(db.session)) -> JSONResponse:  # fmt: skip
    return respond(await svc.list_returns(session, user, branch_id, status), user)


@router.get("/supplier-returns/{return_id}", response_model=SupplierReturnOut)
async def get(return_id: UUID, user: CurrentUser = Depends(perm),
              session: AsyncSession = Depends(db.session)) -> JSONResponse:  # fmt: skip
    return respond(await svc.get(session, user, return_id), user)


@router.post("/supplier-returns/{return_id}/submit", response_model=SupplierReturnOut)
async def submit(
    return_id: UUID, body: SubmitReturnIn, user: CurrentUser = Depends(perm), _: str = Depends(require_idempotency_key),
    session: AsyncSession = Depends(db.session), inventory: InternalClient = Depends(get_inventory),
    auth: InternalClient = Depends(get_auth),
) -> JSONResponse:  # fmt: skip
    """The stock leaves (controlled: PIN + witness); a credit on the supplier's account,
    or (owner / manager) a refund received."""
    return respond(await svc.submit(session, user, inventory, auth, return_id, body.model_dump()), user)


@router.post("/supplier-returns/{return_id}/cancel", response_model=SupplierReturnOut)
async def cancel(return_id: UUID, body: ReasonRequest, user: CurrentUser = Depends(perm),
                 session: AsyncSession = Depends(db.session)) -> JSONResponse:  # fmt: skip
    return respond(await svc.cancel(session, user, return_id, body.reason), user)
