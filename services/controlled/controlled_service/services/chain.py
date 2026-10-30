"""The hash chain. One chain per branch + medicine:

    entry_hash = sha256(prev_hash + canonical JSON of the entry)

The canonical JSON has sorted keys, no spaces, and every field that matters
(quantities, balance, who, witness, Rx, patient, reason, time). The first entry
of a chain has prev_hash = 64 zeros. Appends to one chain wait for each other
(Postgres advisory lock), so balances and hashes never fork.

verify() recomputes every hash and running balance in seq order and reports
the first entry that does not match (edited, deleted or inserted rows).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RegisterEntry

GENESIS = "0" * 64
HASHED = (
    "id", "branch_id", "medicine_id", "batch_id", "lot_no", "expiry_date", "entry_type", "qty_base", "balance_after",
    "ref_type", "ref_id", "movement_id", "prescription_id", "prescription_number", "patient_id", "patient_name",
    "patient_id_document", "actor_id", "actor_name", "witness_id", "witness_name", "reason", "corrects_entry_id",
    "occurred_at",
)  # fmt: skip


def _value(v: Any) -> Any:
    if v is None or isinstance(v, (int, str, bool)):
        return v
    if isinstance(v, datetime):  # the database gives it back in UTC: hash it in UTC
        return v.astimezone(UTC).isoformat(timespec="microseconds")
    return str(v)


def compute_hash(entry: RegisterEntry) -> str:
    body = json.dumps({k: _value(getattr(entry, k)) for k in HASHED}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)  # fmt: skip
    return hashlib.sha256((entry.prev_hash + body).encode()).hexdigest()


def chain_lock_key(branch_id: UUID, medicine_id: UUID) -> int:
    digest = hashlib.sha256(f"register:{branch_id}:{medicine_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def append(session: AsyncSession, entry: RegisterEntry) -> RegisterEntry:
    """Adds the entry at the end of its chain (caller's transaction; caller commits)."""
    await session.execute(
        select(func.pg_advisory_xact_lock(chain_lock_key(entry.branch_id, entry.medicine_id)))
    )
    last = (await session.execute(
        select(RegisterEntry.entry_hash, RegisterEntry.balance_after)
        .where(RegisterEntry.branch_id == entry.branch_id, RegisterEntry.medicine_id == entry.medicine_id)
        .order_by(RegisterEntry.seq.desc()).limit(1))).first()  # fmt: skip
    entry.prev_hash = last.entry_hash if last else GENESIS
    entry.balance_after = (last.balance_after if last else 0) + entry.qty_base
    if entry.id is None:
        entry.id = uuid4()
    entry.entry_hash = compute_hash(entry)
    session.add(entry)
    await session.flush()
    return entry


@dataclass
class ChainResult:
    branch_id: UUID
    medicine_id: UUID
    entries: int
    valid: bool
    first_bad_entry_id: UUID | None = None
    problem: str = ""


async def verify_chain(session: AsyncSession, branch_id: UUID, medicine_id: UUID) -> ChainResult:
    rows = (await session.execute(
        select(RegisterEntry).where(RegisterEntry.branch_id == branch_id, RegisterEntry.medicine_id == medicine_id)
        .order_by(RegisterEntry.seq))).scalars()  # fmt: skip
    prev, balance, count = GENESIS, 0, 0
    for e in rows:
        count += 1
        balance += e.qty_base
        problem = ""
        if e.prev_hash != prev:
            problem = "the previous entry was changed or removed"
        elif e.balance_after != balance:
            problem = "the balance does not add up"
        elif compute_hash(e) != e.entry_hash:
            problem = "this entry was changed after it was written"
        if problem:
            return ChainResult(branch_id, medicine_id, count, False, e.id, problem)
        prev = e.entry_hash
    return ChainResult(branch_id, medicine_id, count, True)


async def verify_all(session: AsyncSession, branch_id: UUID | None = None) -> list[ChainResult]:
    query = select(RegisterEntry.branch_id, RegisterEntry.medicine_id).distinct()
    if branch_id:
        query = query.where(RegisterEntry.branch_id == branch_id)
    return [await verify_chain(session, b, m) for b, m in (await session.execute(query)).all()]
