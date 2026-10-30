from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.visibility import drop_fields

from ..db import db
from ..models import Count, CountLine
from ..schemas.counts import (
    ApproveIn,
    CounterLine,
    CounterView,
    CountOut,
    CountStart,
    EntryIn,
    ReasonIn,
    RecountIn,
    ReviewLine,
    ReviewView,
)
from ..services import counts
from ..services.clients import Clients, get_clients

router = APIRouter(tags=["stock take"])
count_perm = requires("stockcount.count")
approve_perm = requires("stockcount.approve")
see = requires_any("stockcount.count", "stockcount.approve")
COST_FIELDS = frozenset({"cost_per_base", "variance_value"})


def _respond(data: dict[str, Any], user: CurrentUser, status_code: int = 200) -> JSONResponse:
    if not user.has("finance.cost_profit"):
        data = drop_fields(data, COST_FIELDS)
    return JSONResponse(data, status_code=status_code)


def _my(line: CountLine, user: CurrentUser) -> int | None:
    mine = [e for e in line.entries if e.user_id == user.id and e.round == line.round]
    return mine[-1].qty if mine else None


async def _counter_view(session: AsyncSession, count: Count, user: CurrentUser) -> dict[str, Any]:
    out = CounterView.model_validate({**CountOut.model_validate(count).model_dump(), "lines": [
        {**CounterLine.model_validate(x).model_dump(), "my_count": _my(x, user)} for x in count.lines]})  # fmt: skip
    out.progress = await counts.progress(session, count)
    return out.model_dump(mode="json")


async def _review_view(session: AsyncSession, count: Count, user: CurrentUser) -> dict[str, Any]:
    lines = []
    for x in count.lines:
        line = ReviewLine.model_validate(x)
        line.my_count = _my(x, user)
        line.variance_value = x.variance_value
        line.counts = [{"user_id": str(e.user_id), "qty": e.qty, "round": e.round, "counted_at": e.counted_at.isoformat()}
                       for e in x.entries]  # fmt: skip
        lines.append(line)
    out = ReviewView.model_validate({**CountOut.model_validate(count).model_dump(), "lines": lines})
    out.progress = await counts.progress(session, count)
    return out.model_dump(mode="json")


@router.post("/counts", response_model=CounterView, status_code=201)
async def start_count(
    body: CountStart, user: CurrentUser = Depends(count_perm), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> JSONResponse:  # fmt: skip
    """Snapshot the scope (full, category, shelf location or controlled) and start counting."""
    count = await counts.start(session, user, clients, body.model_dump())
    return _respond(await _counter_view(session, count, user), user, 201)


@router.get("/counts", response_model=list[CountOut])
async def list_counts(
    branch_id: UUID | None = None, status: str | None = Query(default=None, max_length=12),
    user: CurrentUser = Depends(see), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    rows = await counts.list_counts(session, user, branch_id, status)
    return JSONResponse([drop_fields(CountOut.model_validate(c).model_dump(mode="json"), COST_FIELDS)
                         if not user.has("finance.cost_profit") else CountOut.model_validate(c).model_dump(mode="json")
                         for c in rows])  # fmt: skip


@router.get("/counts/{count_id}", response_model=CounterView)
async def counter_view(
    count_id: UUID, user: CurrentUser = Depends(count_perm), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """For counters (blind): lots, expiry, location, status and your own count."""
    return _respond(await _counter_view(session, await counts.get_count(session, user, count_id), user), user)


@router.get("/counts/{count_id}/review", response_model=ReviewView)
async def review_view(
    count_id: UUID, user: CurrentUser = Depends(approve_perm), session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    """For approvers: expected, counted, variance (value only with finance.cost_profit), every count."""
    return _respond(await _review_view(session, await counts.get_count(session, user, count_id), user), user)


@router.get("/counts/{count_id}/lookup", response_model=list[CounterLine])
async def lookup(
    count_id: UUID, barcode: str = Query(min_length=1, max_length=48),
    user: CurrentUser = Depends(count_perm), session: AsyncSession = Depends(db.session),
) -> list[dict]:  # fmt: skip
    """Scan a barcode (or type the SKU): the lots of that medicine on this stock take, no quantities."""
    return [{**CounterLine.model_validate(x).model_dump(), "my_count": _my(x, user)}
            for x in await counts.lookup(session, user, count_id, barcode)]  # fmt: skip


@router.post("/counts/{count_id}/entries", response_model=CounterLine)
async def add_entry(
    count_id: UUID, body: EntryIn, user: CurrentUser = Depends(count_perm),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Record what you counted (counting again replaces your own earlier count)."""
    line = await counts.add_entry(session, user, count_id, body.model_dump())
    return {**CounterLine.model_validate(line).model_dump(), "my_count": _my(line, user)}


@router.post("/counts/{count_id}/submit", response_model=ReviewView)
async def submit(
    count_id: UUID, user: CurrentUser = Depends(count_perm), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> JSONResponse:  # fmt: skip
    count = await counts.submit(session, user, clients, count_id)
    if not user.has("stockcount.approve"):
        return _respond(await _counter_view(session, count, user), user)
    return _respond(await _review_view(session, count, user), user)


@router.post("/counts/{count_id}/recount", response_model=ReviewView)
async def recount(
    count_id: UUID, body: RecountIn, user: CurrentUser = Depends(approve_perm),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    count = await counts.send_back(session, user, count_id, body.line_ids, body.reason)
    return _respond(await _review_view(session, count, user), user)


@router.post("/counts/{count_id}/approve", response_model=ReviewView)
async def approve(
    count_id: UUID, body: ApproveIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(approve_perm), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> JSONResponse:  # fmt: skip
    """Posts the variances to stock (count_adjust movements). PIN when a controlled line
    has a variance; above the branch limit (200 USD) only the owner."""
    count = await counts.approve(session, user, clients, count_id, body.pin_token)
    return _respond(await _review_view(session, count, user), user)


@router.post("/counts/{count_id}/cancel", response_model=CountOut)
async def cancel(
    count_id: UUID, body: ReasonIn, user: CurrentUser = Depends(approve_perm),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:  # fmt: skip
    count = await counts.cancel(session, user, count_id, body.reason)
    return _respond(CountOut.model_validate(count).model_dump(mode="json"), user)
