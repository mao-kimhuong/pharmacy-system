"""PIN step-up for sensitive steps (controlled drugs, count approval, shrinkage).

The user types their PIN in the auth service (`POST /api/auth/v1/pin/verify`,
or `/pin/witness` for a second person on the same device) and gets a one-time
`pin_token` (2 minutes, bound to the person and the action). The service doing
the step sends the token here; auth deletes it as it answers, so a token works
once. Services never see a PIN.

    actor = await consume_pin(auth, token, "controlled.adjust", user=user, branch_id=b)
    witness = await consume_witness(auth, token, "controlled.adjust", actor=user, branch_id=b)

Errors: no token → PIN_REQUIRED (401) / WITNESS_REQUIRED (422); unknown, used,
expired, another person's or another action's token → PIN_INVALID (401);
witness = the same person, not at the branch, without `controlled.witness` or
(when `roles` is given, e.g. destruction) not in one of those roles → WITNESS_INVALID (422).
"""

from dataclasses import dataclass
from uuid import UUID

from .auth import ALL_PERMISSIONS, CurrentUser
from .errors import AppError, ErrorCode
from .internal import InternalClient


@dataclass(frozen=True)
class PinPerson:
    user_id: UUID
    name: str
    role: str
    is_pharmacist: bool
    branch_ids: frozenset[UUID]
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        return ALL_PERMISSIONS in self.permissions or permission in self.permissions

    def works_at(self, branch_id: UUID) -> bool:
        return self.role == "owner" or branch_id in self.branch_ids


async def _consume(auth: InternalClient, token: str, action: str, kind: str, actor: CurrentUser) -> PinPerson:
    data = await auth.post("/pin-tokens/consume", {"token": token, "action": action, "kind": kind}, actor=actor)
    return PinPerson(
        user_id=UUID(data["user_id"]), name=data.get("name") or "", role=data["role"],
        is_pharmacist=bool(data["is_pharmacist"]), branch_ids=frozenset(UUID(b) for b in data["branch_ids"]),
        permissions=frozenset(data["permissions"]),
    )  # fmt: skip


async def consume_pin(
    auth: InternalClient, token: str | None, action: str, *, user: CurrentUser, branch_id: UUID
) -> PinPerson:
    """The acting user's own PIN, typed just now for this action."""
    if not token:
        raise AppError(ErrorCode.PIN_REQUIRED, "Type your PIN to confirm", status_code=401,
                       details={"action": action})  # fmt: skip
    person = await _consume(auth, token, action, "actor", user)
    if person.user_id != user.id:
        raise AppError(ErrorCode.PIN_INVALID, "This PIN confirmation belongs to someone else", status_code=401)
    if not person.works_at(branch_id):
        raise AppError(ErrorCode.BRANCH_FORBIDDEN, "You do not work at this branch", status_code=403)
    return person


DESTRUCTION_WITNESS_ROLES = ("branch_manager", "owner")


async def consume_witness(
    auth: InternalClient, token: str | None, action: str, *, actor: CurrentUser, branch_id: UUID,
    roles: tuple[str, ...] | None = None, permission: str = "controlled.witness",
) -> PinPerson:  # fmt: skip
    """A second staff member's PIN: not the actor, works at the branch, may witness
    (and, when `roles` is given, has one of those roles)."""
    if not token:
        raise AppError(ErrorCode.WITNESS_REQUIRED, "A second staff member must witness this with their PIN",
                       status_code=422, details={"action": action})  # fmt: skip
    person = await _consume(auth, token, action, "witness", actor)
    if person.user_id == actor.id:
        raise AppError(ErrorCode.WITNESS_INVALID, "The witness must be another person", status_code=422)
    if not person.works_at(branch_id) or not person.has(permission):
        raise AppError(ErrorCode.WITNESS_INVALID, f"{person.name or 'This person'} cannot witness at this branch",
                       status_code=422)  # fmt: skip
    if roles and person.role not in roles:
        who = " or ".join({"branch_manager": "a branch manager", "owner": "the owner"}.get(r, r) for r in roles)
        raise AppError(ErrorCode.WITNESS_INVALID, f"This needs {who} to confirm with their PIN", status_code=422,
                       details={"witness_roles": list(roles)})  # fmt: skip
    return person
