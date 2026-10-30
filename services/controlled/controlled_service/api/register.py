from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..models import AdjustRequest, Discrepancy, RegisterEntry
from ..schemas.register import (
    AdjustIn,
    AdjustOut,
    CorrectionIn,
    DiscrepancyOut,
    EntryOut,
    RegisterOut,
    ResolveIn,
    VerifyOut,
)
from ..services import chain, entries, reconcile, register
from ..services.clients import Clients, get_clients

router = APIRouter(tags=["register"])
view = requires("controlled.view")


@router.get("/register", response_model=RegisterOut)
async def get_register(
    branch_id: UUID, medicine_id: UUID | None = None,
    date_from: date | None = Query(default=None, alias="from"), date_to: date | None = Query(default=None, alias="to"),
    user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """The running register (oldest first) with balance_after and chain_valid."""
    user.require_branch(branch_id)
    return await register.entries(session, branch_id, medicine_id, date_from, date_to)


@router.get("/register/verify", response_model=VerifyOut)
async def verify(
    branch_id: UUID, user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Recomputes every hash and balance of the branch's chains."""
    user.require_branch(branch_id)
    chains = await chain.verify_all(session, branch_id)
    return {"valid": all(c.valid for c in chains), "chains": [c.__dict__ for c in chains]}


@router.post("/entries", response_model=AdjustOut, status_code=201)
async def adjust_or_destroy(
    body: AdjustIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("controlled.adjust")), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> AdjustRequest:  # fmt: skip
    """Adjust or destroy controlled stock: your PIN (action controlled.adjust or
    controlled.destroy) + a witness's PIN, a reason; destroy needs the method."""
    return await entries.adjust(session, user, clients, body.model_dump())


@router.post("/entries/correction", response_model=EntryOut, status_code=201)
async def correction(
    body: CorrectionIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("controlled.adjust")), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> RegisterEntry:  # fmt: skip
    """A new row that corrects an earlier one (which stays unchanged). PIN + witness."""
    return await entries.correct(session, user, clients, body.model_dump())


@router.get("/discrepancies", response_model=list[DiscrepancyOut])
async def list_discrepancies(
    branch_id: UUID | None = None, status: str = Query(default="open", max_length=10),
    user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session),
) -> list[Discrepancy]:  # fmt: skip
    query = select(Discrepancy).where(Discrepancy.status == status)
    if branch_id:
        user.require_branch(branch_id)
        query = query.where(Discrepancy.branch_id == branch_id)
    elif not user.is_owner:
        query = query.where(Discrepancy.branch_id.in_(list(user.branch_ids)))
    return list((await session.execute(query.order_by(Discrepancy.found_at.desc()))).scalars())


@router.post("/discrepancies/{discrepancy_id}/resolve", response_model=DiscrepancyOut)
async def resolve(
    discrepancy_id: UUID, body: ResolveIn, user: CurrentUser = Depends(requires("controlled.resolve")),
    session: AsyncSession = Depends(db.session), clients: Clients = Depends(get_clients),
) -> Discrepancy:  # fmt: skip
    """Explain it (PIN + witness); optionally add a correction entry so register = stock."""
    return await reconcile.resolve(session, user, clients, discrepancy_id, body.model_dump())
