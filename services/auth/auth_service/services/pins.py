"""PIN step-up: the person types their PIN for one sensitive action and gets a
one-time token that another service consumes (pharmacy_shared.pin). Rules:

- `verify`: the logged-in user's own PIN → token bound to them and the action.
- `witness`: a second person's PIN typed on the same device → token bound to
  the witness, the action, and the user who asked (they consume it).
- 5 wrong PINs in a row lock that person's PIN for 15 minutes (PIN_LOCKED, 423;
  User Log `user.pin_locked`); a right PIN resets the count.
- Tokens live 2 minutes in Redis (only a hash of the token is stored) and are
  deleted when consumed (GETDEL): a token works once, for its action only.
- No PIN set → PIN_REQUIRED with a hint to set it on the profile.
"""

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import User
from .access import load_permissions
from .audit import write_audit
from .passwords import verify_password

TOKEN_SECONDS = 120
MAX_FAILURES = 5
LOCK_MINUTES = 15
ACTION = re.compile(r"^[a-z_]+\.[a-z_]+$")


def _key(token: str) -> str:
    return "pin:" + hashlib.sha256(token.encode()).hexdigest()


def _branch(user: User) -> UUID | None:
    return user.branch_ids[0] if user.branch_ids else None


async def _check_pin(session: AsyncSession, user: User, pin: str, action: str, ip: str | None) -> None:
    now = datetime.now(UTC)
    if user.pin_locked_until and user.pin_locked_until > now:
        raise AppError(ErrorCode.PIN_LOCKED, f"{user.name}'s PIN is locked; try again after "
                       f"{LOCK_MINUTES} minutes", status_code=423,
                       details={"locked_until": user.pin_locked_until.isoformat()})  # fmt: skip
    if user.pin_hash is None:
        raise AppError(ErrorCode.PIN_REQUIRED, f"{user.name} has no PIN yet: set it on the profile first",
                       status_code=401)  # fmt: skip
    if verify_password(user.pin_hash, pin):
        user.pin_failed_count, user.pin_locked_until = 0, None
        return
    user.pin_failed_count += 1
    locked = user.pin_failed_count >= MAX_FAILURES
    if locked:
        user.pin_failed_count, user.pin_locked_until = 0, now + timedelta(minutes=LOCK_MINUTES)
        write_audit(session, action="user.pin_locked", entity_type="user", entity_id=user.id, actor_id=user.id,
                    actor_role=user.role, branch_id=_branch(user), after={"action": action}, ip=ip,
                    only_changes=False)  # fmt: skip
    await session.commit()
    if locked:
        raise AppError(ErrorCode.PIN_LOCKED, f"5 wrong PINs: {user.name}'s PIN is locked for {LOCK_MINUTES} minutes",
                       status_code=423)  # fmt: skip
    raise AppError(ErrorCode.PIN_INVALID, "Wrong PIN", status_code=401,
                   details={"attempts_left": MAX_FAILURES - user.pin_failed_count})  # fmt: skip


async def _issue(redis: Redis, user: User, action: str, kind: str, for_user: UUID) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    value = {"user_id": str(user.id), "action": action, "kind": kind, "for_user": str(for_user)}
    await redis.set(_key(token), json.dumps(value), ex=TOKEN_SECONDS)
    return {"pin_token": token, "expires_at": datetime.now(UTC) + timedelta(seconds=TOKEN_SECONDS),
            "user_id": user.id, "name": user.name}  # fmt: skip


def _action(action: str) -> str:
    if not ACTION.match(action):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Unknown action", status_code=422)
    return action


async def _active_user(session: AsyncSession, user_id: UUID) -> User:
    user = (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AppError(ErrorCode.NOT_FOUND, "Staff member not found", status_code=404)
    return user


async def verify(
    session: AsyncSession, redis: Redis, actor: CurrentUser, pin: str, action: str, ip: str | None
) -> dict[str, Any]:
    user = await _active_user(session, actor.id)
    await _check_pin(session, user, pin, _action(action), ip)
    await session.commit()
    return await _issue(redis, user, action, "actor", actor.id)


async def witness(
    session: AsyncSession, redis: Redis, actor: CurrentUser, witness_id: UUID, pin: str, action: str,
    ip: str | None,
) -> dict[str, Any]:  # fmt: skip
    if witness_id == actor.id:
        raise AppError(ErrorCode.WITNESS_INVALID, "The witness must be another person", status_code=422)
    user = await _active_user(session, witness_id)
    if not (user.role == "owner" or set(user.branch_ids) & set(actor.branch_ids) or actor.is_owner):
        raise AppError(ErrorCode.WITNESS_INVALID, "The witness does not work at your branch", status_code=422)
    await _check_pin(session, user, pin, _action(action), ip)
    await session.commit()
    return await _issue(redis, user, action, "witness", actor.id)


async def consume(session: AsyncSession, redis: Redis, token: str, action: str, kind: str,
                  acting_user: UUID | None) -> dict[str, Any]:  # fmt: skip
    """For other services (/internal/v1/pin-tokens/consume): deletes the token."""
    raw = await redis.getdel(_key(token))
    invalid = AppError(ErrorCode.PIN_INVALID, "The PIN confirmation is not valid any more; type the PIN again",
                       status_code=401)  # fmt: skip
    if raw is None:
        raise invalid
    data = json.loads(raw)
    if data["action"] != action or data["kind"] != kind or (acting_user and data["for_user"] != str(acting_user)):
        raise invalid
    user = await session.get(User, UUID(data["user_id"]))
    if user is None or not user.is_active:
        raise invalid
    return {"user_id": str(user.id), "name": user.name, "role": user.role, "is_pharmacist": user.is_pharmacist,
            "branch_ids": [str(b) for b in user.branch_ids],
            "permissions": await load_permissions(session, user.role)}  # fmt: skip


async def witnesses(session: AsyncSession, actor: CurrentUser, branch_id: UUID) -> list[User]:
    """Who can be picked as witness at a branch: active, has a PIN (the
    controlled.witness permission is checked when the token is used)."""
    actor.require_branch(branch_id)
    rows = (await session.execute(select(User).where(User.is_active.is_(True), User.pin_hash.is_not(None))
                                  .order_by(User.name))).scalars()  # fmt: skip
    return [u for u in rows if u.id != actor.id and (branch_id in u.branch_ids or u.role == "owner")]
