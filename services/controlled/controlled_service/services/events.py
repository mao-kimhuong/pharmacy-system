"""Events the controlled service listens to (queue `controlled.events`).

- branch.*      → branches
- medicine.*    → medicines (controlled flag, names; older versions ignored)
- user.*        → staff names for the register
- stock.changed → one register entry per movement of a controlled medicine
                  (once per movement id). Who, witness, Rx and patient come
                  from the movement's `meta`.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import copies

from ..models import ControlledProduct, KnownBranch, KnownStaff, RegisterEntry, Watermark
from .chain import append

ROUTING_KEYS = ("branch.*", "medicine.*", "user.*", "stock.changed")
USER_EVENTS = frozenset({"user.created", "user.updated", "user.activated", "user.deactivated"})
# inventory movement type → register entry type (meta.entry_type wins when given)
ENTRY_TYPE = {
    "in": "receive", "opening": "opening", "out": "dispense", "sale_cancel": "sale_cancel",
    "return": "customer_return", "adjust_in": "adjust", "adjust_out": "adjust", "expire_writeoff": "expired",
    "transfer_in": "transfer_in", "transfer_out": "transfer_out", "shrinkage": "destroy",
    "count_adjust": "count_adjust",
}  # fmt: skip


def _uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value else None


async def upsert_product(session: AsyncSession, p: dict[str, Any]) -> bool:
    product_id = UUID(str(p["medicine_id"]))
    stored = (await session.execute(select(ControlledProduct.version).where(ControlledProduct.id == product_id))
              ).scalar_one_or_none()  # fmt: skip
    if stored is not None and stored >= int(p["version"]):
        return False
    brand, generic = p["brand_name"], p["generic_name"]
    values = {
        "id": product_id, "version": int(p["version"]), "sku": p["sku"],
        "name": brand if brand.casefold() == generic.casefold() else f"{brand} ({generic})",
        "name_km": p.get("name_km") or "", "strength": p.get("strength") or "", "base_unit": p["base_unit"],
        "controlled_schedule": p.get("controlled_schedule"), "is_active": bool(p["is_active"]),
    }  # fmt: skip
    await session.execute(insert(ControlledProduct).values(**values).on_conflict_do_update(
        index_elements=[ControlledProduct.id], set_={k: v for k, v in values.items() if k != "id"}))  # fmt: skip
    return True


async def record_movement(session: AsyncSession, p: dict[str, Any]) -> RegisterEntry | None:
    """stock.changed → register entry; None for other medicines or a movement already recorded."""
    if not p.get("is_controlled"):
        return None
    movement_id = UUID(str(p["movement_id"]))
    if (
        await session.execute(select(RegisterEntry.id).where(RegisterEntry.movement_id == movement_id))
    ).first():
        return None
    meta = p.get("meta") or {}
    actor_id = _uuid(meta.get("pharmacist_id") or p.get("created_by"))
    actor = await session.get(KnownStaff, actor_id) if actor_id else None
    occurred = datetime.fromisoformat(p["occurred_at"]) if p.get("occurred_at") else datetime.now(UTC)
    entry = RegisterEntry(
        branch_id=UUID(p["branch_id"]), medicine_id=UUID(p["medicine_id"]), batch_id=UUID(p["batch_id"]),
        lot_no=p.get("lot_no") or "", expiry_date=date.fromisoformat(p["expiry_date"]) if p.get("expiry_date") else None,
        entry_type=meta.get("entry_type") or ENTRY_TYPE.get(p["type"], "adjust"), qty_base=int(p["delta"]),
        ref_type=p.get("ref_type") or "", ref_id=str(p.get("ref_id") or ""), movement_id=movement_id,
        movement_seq=p.get("seq"), prescription_id=_uuid(meta.get("prescription_id")),
        prescription_number=meta.get("prescription_number") or "", patient_id=_uuid(meta.get("patient_id")),
        patient_name=meta.get("patient_name") or "", patient_id_document=meta.get("patient_id_document") or "",
        actor_id=actor_id, actor_name=meta.get("pharmacist_name") or meta.get("actor_name") or (actor.name if actor else ""),
        witness_id=_uuid(meta.get("witness_id")), witness_name=meta.get("witness_name") or "",
        reason=(p.get("reason") or "")[:255], occurred_at=occurred,
    )  # fmt: skip
    return await append(session, entry)


async def handle_event(
    session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID
) -> None:
    if event_type in copies.BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif event_type in copies.MEDICINE_EVENTS:
        await upsert_product(session, payload)
    elif event_type in USER_EVENTS:
        values = {"id": UUID(payload["user_id"]), "name": payload.get("name") or "",
                  "is_active": bool(payload.get("is_active", True))}  # fmt: skip
        await session.execute(insert(KnownStaff).values(**values).on_conflict_do_update(
            index_elements=[KnownStaff.id], set_={k: v for k, v in values.items() if k != "id"}))  # fmt: skip
    elif event_type == "stock.changed":
        await record_movement(session, payload)
        if payload.get("seq"):
            await session.execute(insert(Watermark).values(id=1, last_seq=int(payload["seq"])).on_conflict_do_update(
                index_elements=[Watermark.id], set_={"last_seq": func.greatest(Watermark.last_seq, int(payload["seq"]))}))  # fmt: skip
