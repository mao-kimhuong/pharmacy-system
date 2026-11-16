"""Approvals decided outside the app (T2: a Telegram button), shared by the services that own them.

The notification service checks who tapped (their linked Telegram user → auth's /internal/v1/users/{id}/access,
right now: active, permission, branch, value limit, nothing controlled or PIN-bound) and then calls the owning
service's `POST /internal/v1/<thing>/{id}/decide` with that access. The service turns it into a CurrentUser and runs
its OWN approve / reject rules (state, someone else than the requester, owner limits…), so the app and Telegram
follow the same rules; the User Log entry says `"via": "telegram"`. Idempotent by state: deciding twice → the
service's *_STATE error (409), which notification reads as "already decided".
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .auth import CurrentUser

VIA_TELEGRAM = "telegram"


class Actor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: UUID
    name: str = ""
    role: str
    is_active: bool = True
    is_pharmacist: bool = False
    branch_ids: list[UUID] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    actor: Actor
    reason: str = Field(default="Rejected on Telegram", min_length=1, max_length=255)


def acting_user(actor: Actor) -> CurrentUser:
    return CurrentUser(id=actor.user_id, role=actor.role, branch_ids=frozenset(actor.branch_ids),
                       is_pharmacist=actor.is_pharmacist, permissions=frozenset(actor.permissions))  # fmt: skip
