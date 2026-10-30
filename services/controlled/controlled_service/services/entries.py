"""Manual register work. Rules:

- Adjust or destroy (controlled.adjust): the user's PIN and a witness's PIN
  (another person of the branch with controlled.witness), a reason; destroy
  also needs the destruction method. Inventory makes the movement (once per
  request); its register entry arrives with the stock.changed event.
- Correction (controlled.adjust, PIN + witness): a register-only row pointing
  at the entry it corrects (signed quantity, may be 0 for a note). The wrong
  entry stays as it was.
"""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.pin import consume_pin, consume_witness

from ..models import AdjustRequest, KnownBranch, RegisterEntry
from .chain import append
from .clients import Clients
from .common import audit, clean, not_found


async def _branch(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> KnownBranch:
    actor.require_branch(branch_id)
    branch = await session.get(KnownBranch, branch_id)
    if branch is None or not branch.is_active:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Unknown or inactive branch", status_code=422)
    return branch


async def adjust(
    session: AsyncSession, actor: CurrentUser, clients: Clients, data: dict[str, Any]
) -> AdjustRequest:
    branch = await _branch(session, actor, data["branch_id"])
    action = "controlled.destroy" if data["kind"] == "destroy" else "controlled.adjust"
    if data["kind"] == "destroy" and not clean(data.get("destruction_method")):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Give the destruction method", status_code=422,
                       details={"field": "destruction_method"})  # fmt: skip
    me = await consume_pin(clients.auth, data.get("pin_token"), action, user=actor, branch_id=branch.id)
    witness = await consume_witness(
        clients.auth, data.get("witness_token"), action, actor=actor, branch_id=branch.id
    )
    req = AdjustRequest(id=uuid4(), branch_id=branch.id, batch_id=data["batch_id"], kind=data["kind"],
                        qty_base=data["qty_base"], reason=clean(data["reason"]),
                        destruction_method=clean(data.get("destruction_method")), actor_id=actor.id,
                        witness_id=witness.user_id, witness_name=witness.name)  # fmt: skip
    moved = await clients.inventory.post("/movements/controlled", {
        "request_id": str(req.id), "branch_id": str(branch.id), "batch_id": str(req.batch_id), "kind": req.kind,
        "qty_base": req.qty_base, "reason": req.reason,
        "meta": {"entry_type": "destroy" if req.kind == "destroy" else "adjust", "actor_name": me.name,
                 "witness_id": str(witness.user_id), "witness_name": witness.name,
                 "destruction_method": req.destruction_method, "request_id": str(req.id)},
    }, actor=actor, branch_id=branch.id)  # fmt: skip
    req.movement_id = UUID(str(moved["movement_id"]))
    session.add(req)
    audit(session, actor, f"register.{req.kind}", "batch", req.batch_id, branch_id=branch.id, after={
        "qty_base": req.qty_base, "reason": req.reason, "witness": witness.name,
        "destruction_method": req.destruction_method or None})  # fmt: skip
    await session.commit()
    return req


async def correct(
    session: AsyncSession, actor: CurrentUser, clients: Clients, data: dict[str, Any]
) -> RegisterEntry:
    wrong = await session.get(RegisterEntry, data["corrects_entry_id"])
    if wrong is None or not actor.can_access_branch(wrong.branch_id):
        raise not_found("Register entry")
    me = await consume_pin(clients.auth, data.get("pin_token"), "controlled.adjust", user=actor,
                           branch_id=wrong.branch_id)  # fmt: skip
    witness = await consume_witness(clients.auth, data.get("witness_token"), "controlled.adjust", actor=actor,
                                    branch_id=wrong.branch_id)  # fmt: skip
    entry = await append(session, RegisterEntry(
        branch_id=wrong.branch_id, medicine_id=wrong.medicine_id, batch_id=wrong.batch_id, lot_no=wrong.lot_no,
        expiry_date=wrong.expiry_date, entry_type="correction", qty_base=data["qty_base"], ref_type="correction",
        ref_id=str(wrong.id), actor_id=actor.id, actor_name=me.name, witness_id=witness.user_id,
        witness_name=witness.name, reason=clean(data["reason"]), corrects_entry_id=wrong.id, occurred_at=clock.now(),
    ))  # fmt: skip
    audit(session, actor, "register.correction", "register_entry", entry.id, branch_id=entry.branch_id, after={
        "corrects": str(wrong.id), "qty_base": entry.qty_base, "reason": entry.reason, "witness": witness.name})  # fmt: skip
    await session.commit()
    return entry
