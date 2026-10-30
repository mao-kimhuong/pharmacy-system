"""Shrinkage: stock written off as expired, damaged, broken, lost/stolen or
recalled. Rules:

- inventory.shrinkage, own branch, Idempotency-Key. Value = qty × the batch's
  cost per base unit.
- Controlled medicine: the user's PIN and a witness's PIN (another person of
  the branch with controlled.witness; a destruction – any reason except
  lost/stolen – needs a branch manager or the owner as witness) → both recorded; the movement carries
  them to the controlled-drug register. A destruction method is required.
- Value above the branch's `shrinkage_approval_usd` (50 by default) → pending;
  someone else with inventory.shrinkage_approve approves (posted) or rejects
  (reason). Nothing leaves stock until posted; posting checks stock then.
- Posted = one "shrinkage" movement (once per shrinkage). Never deleted.
- A photo (JPEG/PNG/PDF ≤ 10 MB, checked by content) can be added; it is read
  only through this service (permission + branch checked, logged each time).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.numbering import next_number
from pharmacy_shared.pin import DESTRUCTION_WITNESS_ROLES, consume_pin, consume_witness
from pharmacy_shared.storage import Storage
from pharmacy_shared.uploads import check_upload

from ..models import Batch, BranchSettingsCopy, DocSequence, Product, Shrinkage, Stock
from .common import audit, branch_for, clean
from .movements import apply_movement, lock_stock

DEFAULT_LIMIT = Decimal("50.00")
ACTION = "inventory.shrinkage"


def _state(message: str, status: str) -> AppError:
    return AppError(ErrorCode.SHRINKAGE_STATE, message, status_code=409, details={"status": status})


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Shrinkage not found", status_code=404)


async def get(
    session: AsyncSession, actor: CurrentUser, shrinkage_id: UUID, *, lock: bool = False
) -> Shrinkage:
    query = select(Shrinkage).where(Shrinkage.id == shrinkage_id)
    s = (await session.execute(query.with_for_update(of=Shrinkage) if lock else query)).scalar_one_or_none()
    if s is None or not actor.can_access_branch(s.branch_id):
        raise _not_found()
    return s


@dataclass(frozen=True)
class ShrinkageFilter:
    branch_id: UUID | None = None
    status: str | None = None


async def list_shrinkages(
    session: AsyncSession, actor: CurrentUser, f: ShrinkageFilter, page: int, size: int
):  # noqa: ANN201
    query = select(Shrinkage)
    if f.branch_id:
        actor.require_branch(f.branch_id)
        query = query.where(Shrinkage.branch_id == f.branch_id)
    elif not actor.is_owner:
        query = query.where(Shrinkage.branch_id.in_(list(actor.branch_ids) or [uuid4()]))
    if f.status:
        query = query.where(Shrinkage.status == f.status)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(Shrinkage.created_at.desc(), Shrinkage.id)
                                 .offset((page - 1) * size).limit(size))  # fmt: skip
    return list(rows.scalars()), int(total)


async def _post(session: AsyncSession, actor: CurrentUser, s: Shrinkage) -> None:
    move = await apply_movement(
        session, branch_id=s.branch_id, batch=s.batch, type="shrinkage", qty_base=-s.qty_base,
        ref_type="shrinkage", ref_id=str(s.id), reason=f"{s.number} {s.reason}: {s.note}"[:255],
        actor_id=s.created_by, meta=s.meta,
    )  # fmt: skip
    s.status, s.movement_id = "posted", move.id


async def create(
    session: AsyncSession, actor: CurrentUser, auth: InternalClient, data: dict[str, Any]
) -> Shrinkage:
    branch = await branch_for(session, actor, data["branch_id"])
    batch = await session.get(Batch, data["batch_id"])
    if batch is None:
        raise AppError(ErrorCode.NOT_FOUND, "Batch not found", status_code=404)
    product = await session.get(Product, batch.medicine_id)
    controlled = bool(product and product.controlled_schedule)
    stock = (await session.execute(select(Stock).where(Stock.branch_id == branch.id, Stock.batch_id == batch.id))
             ).scalar_one_or_none()  # fmt: skip
    free = (stock.qty_on_hand - stock.qty_reserved) if stock else 0
    if data["qty_base"] > free:
        raise AppError(ErrorCode.OUT_OF_STOCK, f"Only {free} of lot {batch.lot_no} can be written off",
                       status_code=409, details={"available": free})  # fmt: skip
    meta: dict[str, Any] = {"reason": data["reason"], "note": clean(data.get("note"))}
    witness = None
    if controlled:
        if not clean(data.get("destruction_method")):
            raise AppError(ErrorCode.VALIDATION_ERROR, "Give the destruction method for a controlled medicine",
                           status_code=422, details={"field": "destruction_method"})  # fmt: skip
        await consume_pin(auth, data.get("pin_token"), ACTION, user=actor, branch_id=branch.id)
        destroyed = data["reason"] != "lost_theft"
        witness = await consume_witness(auth, data.get("witness_token"), ACTION, actor=actor, branch_id=branch.id,
                                        roles=DESTRUCTION_WITNESS_ROLES if destroyed else None)  # fmt: skip
        meta.update(entry_type="destroy" if data["reason"] != "lost_theft" else "loss",
                    witness_id=str(witness.user_id), witness_name=witness.name,
                    destruction_method=clean(data.get("destruction_method")), pin_confirmed=True)  # fmt: skip
    value = (batch.cost_per_base * data["qty_base"]).quantize(Decimal("0.01"))
    settings = await session.get(BranchSettingsCopy, branch.id)
    limit = settings.shrinkage_approval_usd if settings else DEFAULT_LIMIT
    s = Shrinkage(
        branch_id=branch.id, batch_id=batch.id, medicine_id=batch.medicine_id, qty_base=data["qty_base"],
        reason=data["reason"], note=clean(data.get("note")), destruction_method=clean(data.get("destruction_method")),
        value=value, status="pending_approval", is_controlled=controlled, batch=batch,
        witness_id=witness.user_id if witness else None, witness_name=witness.name if witness else "",
        created_by=actor.id, meta=meta,
    )  # fmt: skip
    s.number = await next_number(session, DocSequence, branch.id, branch.code, "SH")
    session.add(s)
    await session.flush()
    meta["shrinkage_id"], meta["number"] = str(s.id), s.number
    s.meta = dict(meta)
    if value <= limit:
        await _post(session, actor, s)
    audit(session, actor, "shrinkage.created", "shrinkage", s.id, branch_id=branch.id, after={
        "number": s.number, "lot_no": batch.lot_no, "qty_base": s.qty_base, "reason": s.reason, "value": str(value),
        "status": s.status, "witness": s.witness_name or None})  # fmt: skip
    await session.commit()
    return s


async def approve(session: AsyncSession, actor: CurrentUser, shrinkage_id: UUID) -> Shrinkage:
    s = await get(session, actor, shrinkage_id, lock=True)
    if s.status != "pending_approval":
        raise _state(f"This shrinkage is {s.status.replace('_', ' ')}", s.status)
    if s.created_by == actor.id and not actor.is_owner:
        raise AppError(ErrorCode.FORBIDDEN, "Someone else must approve your own shrinkage", status_code=403)
    await lock_stock(session, s.branch_id, s.batch_id)
    s.decided_by, s.decided_at = actor.id, clock.now()
    await _post(session, actor, s)
    audit(session, actor, "shrinkage.approved", "shrinkage", s.id, branch_id=s.branch_id,
          after={"number": s.number, "value": str(s.value)})  # fmt: skip
    await session.commit()
    return s


async def reject(session: AsyncSession, actor: CurrentUser, shrinkage_id: UUID, reason: str) -> Shrinkage:
    s = await get(session, actor, shrinkage_id, lock=True)
    if s.status != "pending_approval":
        raise _state(f"This shrinkage is {s.status.replace('_', ' ')}", s.status)
    s.status, s.reject_reason, s.decided_by, s.decided_at = "rejected", clean(reason), actor.id, clock.now()
    audit(session, actor, "shrinkage.rejected", "shrinkage", s.id, branch_id=s.branch_id,
          after={"number": s.number, "reason": s.reject_reason})  # fmt: skip
    await session.commit()
    return s


async def add_photo(session: AsyncSession, actor: CurrentUser, storage: Storage, shrinkage_id: UUID,
                    data: bytes) -> Shrinkage:  # fmt: skip
    s = await get(session, actor, shrinkage_id, lock=True)
    if s.status == "rejected":
        raise _state("A rejected shrinkage takes no photo", s.status)
    clean_file = check_upload(data)
    key = f"shrinkage/{uuid4()}"
    await storage.put(key, clean_file.data, clean_file.content_type)
    s.photo_key, s.photo_type = key, clean_file.content_type
    audit(session, actor, "shrinkage.photo_added", "shrinkage", s.id, branch_id=s.branch_id,
          after={"type": s.photo_type, "bytes": len(clean_file.data)})  # fmt: skip
    await session.commit()
    return s


async def read_photo(session: AsyncSession, actor: CurrentUser, storage: Storage, shrinkage_id: UUID
                     ) -> tuple[Shrinkage, bytes]:  # fmt: skip
    s = await get(session, actor, shrinkage_id)
    if not s.photo_key:
        raise AppError(ErrorCode.NOT_FOUND, "This shrinkage has no photo", status_code=404)
    data = await storage.get(s.photo_key)
    audit(session, actor, "shrinkage.photo_viewed", "shrinkage", s.id, branch_id=s.branch_id)
    await session.commit()
    return s, data
