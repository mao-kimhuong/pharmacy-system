from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.idempotency import require_idempotency_key

from ..db import db
from ..models import AdjustRequest, Discrepancy, RegisterEntry
from ..schemas.register import (
    AdjustIn,
    AdjustOut,
    CorrectionIn,
    DiscrepancyOut,
    EntryDetail,
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


@router.get("/entries/{entry_id}", response_model=EntryDetail)
async def get_entry(entry_id: UUID, user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)) -> dict:
    """One entry with its place in the chain (previous / next), its hash check, and the
    corrections made to it. The source: movement_id, ref_type / ref_id (sale, receipt…)."""
    e = await session.get(RegisterEntry, entry_id)
    if e is None or not user.can_access_branch(e.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Register entry not found", status_code=404)
    chain_of = (RegisterEntry.branch_id == e.branch_id, RegisterEntry.medicine_id == e.medicine_id)
    prev = (await session.execute(select(RegisterEntry).where(*chain_of, RegisterEntry.seq < e.seq)
                                  .order_by(RegisterEntry.seq.desc()).limit(1))).scalar_one_or_none()  # fmt: skip
    nxt = (await session.execute(select(RegisterEntry.id).where(*chain_of, RegisterEntry.seq > e.seq)
                                 .order_by(RegisterEntry.seq).limit(1))).scalar_one_or_none()  # fmt: skip
    linked = (prev.entry_hash if prev else chain.GENESIS) == e.prev_hash
    corrections = list((await session.execute(select(RegisterEntry.id).where(
        RegisterEntry.corrects_entry_id == e.id).order_by(RegisterEntry.seq))).scalars())  # fmt: skip
    return {"entry": e, "prev_entry_id": prev.id if prev else None, "next_entry_id": nxt,
            "hash_valid": linked and chain.compute_hash(e) == e.entry_hash, "corrected_by": corrections}  # fmt: skip


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
