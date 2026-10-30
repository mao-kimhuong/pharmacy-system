"""Settings → User. Rules:

- Staff are never deleted: deactivate / activate.
- The owner manages everyone. Anyone else with `settings.users` (a branch
  manager) manages only staff whose branches are all inside their own branches,
  and only roles they could not use to gain power: not the owner role, no role
  with admin permissions, no permission they do not have themselves.
- Every non-owner user works in at least one branch; branches must exist.
- The last active owner cannot be deactivated or given another role.
- Deactivating, resetting the password, changing role, branches or the
  pharmacist flag logs the user out everywhere at once.
- Every change is written to the User Log with before/after (never secrets).
"""

from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..models import KnownBranch, OutboxEvent, RefreshToken, RoleRecord, User, UserBranch
from ..permissions import ADMIN_PERMISSIONS, OWNER
from . import sessions
from .audit import write_audit
from .passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password
from .phone import normalize_phone

PIN_LENGTHS = range(4, 7)


@dataclass(frozen=True)
class UserFilter:
    q: str | None = None
    role: str | None = None
    branch_id: UUID | None = None
    is_active: bool | None = None


def user_event_payload(user: User) -> dict:
    """What other services keep about staff (pharmacist names on labels). No secrets."""
    loaded = "branches" not in sa_inspect(user).unloaded  # a new owner has none: do not lazy-load
    return {
        "user_id": str(user.id), "name": user.name, "role": user.role, "is_pharmacist": user.is_pharmacist,
        "is_active": user.is_active, "branch_ids": [str(b) for b in user.branch_ids] if loaded else [],
    }  # fmt: skip


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "User not found", status_code=404)


def _forbidden(message: str) -> AppError:
    return AppError(ErrorCode.FORBIDDEN, message, status_code=403)


def _primary_branch(user: User) -> UUID | None:
    ids = user.branch_ids
    return ids[0] if ids else None


def can_manage(actor: CurrentUser, target: User, target_role: RoleRecord | None) -> bool:
    if actor.is_owner:
        return True
    if target.role == OWNER:
        return False
    if target_role is not None and _is_admin_role(target_role):
        return False
    ids = set(target.branch_ids)
    return bool(ids) and ids <= set(actor.branch_ids)


def _is_admin_role(role: RoleRecord) -> bool:
    return role.key == OWNER or bool(ADMIN_PERMISSIONS & set(role.permission_keys))


async def _get_role(session: AsyncSession, key: str) -> RoleRecord:
    role = await session.get(RoleRecord, key)
    if role is None or not role.is_active:
        raise AppError(ErrorCode.UNKNOWN_ROLE, f"Unknown role: {key}", status_code=422)
    return role


def _check_assignable(actor: CurrentUser, role: RoleRecord) -> None:
    if actor.is_owner:
        return
    if _is_admin_role(role):
        raise _forbidden("Only the owner can give this role")
    missing = set(role.permission_keys) - set(actor.permissions)
    if missing and "*" not in actor.permissions:
        raise _forbidden("You cannot give a role with permissions you do not have")


async def _check_branches(
    session: AsyncSession, actor: CurrentUser, role_key: str, branch_ids: list[UUID]
) -> list[UUID]:
    ids = sorted(set(branch_ids), key=str)
    if role_key == OWNER:
        return []  # the owner works in every branch
    if not ids:
        raise AppError(ErrorCode.UNKNOWN_BRANCH, "Choose at least one branch", status_code=422)
    known = await session.execute(
        select(KnownBranch.id).where(KnownBranch.id.in_(ids), KnownBranch.is_active.is_(True))
    )
    missing = set(ids) - set(known.scalars())
    if missing:
        raise AppError(
            ErrorCode.UNKNOWN_BRANCH,
            "Unknown or inactive branch",
            status_code=422,
            details={"branch_ids": sorted(str(b) for b in missing)},
        )
    if not actor.is_owner and not set(ids) <= set(actor.branch_ids):
        raise AppError(ErrorCode.BRANCH_FORBIDDEN, "You can only assign your own branches", status_code=403)
    return ids


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(
            ErrorCode.WEAK_PASSWORD,
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            status_code=422,
        )


def _phone(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except ValueError as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Invalid phone number", status_code=422) from exc


async def _check_phone_free(session: AsyncSession, phone: str, except_id: UUID | None = None) -> None:
    query = select(User.id).where(User.phone == phone)
    if except_id:
        query = query.where(User.id != except_id)
    if (await session.execute(query)).first():
        raise AppError(ErrorCode.DUPLICATE_PHONE, "This phone number is already used", status_code=409)


async def _end_sessions(session: AsyncSession, redis: Redis, user_id: UUID) -> None:
    await sessions.revoke_all_sessions(redis, user_id)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )


async def _active_owner_count(session: AsyncSession) -> int:
    rows = await session.execute(
        select(func.count(User.id)).where(User.role == OWNER, User.is_active.is_(True))
    )
    return int(rows.scalar_one())


async def get_manageable(
    session: AsyncSession, actor: CurrentUser, user_id: UUID, *, lock: bool = False
) -> User:
    query = select(User).where(User.id == user_id)
    if lock:
        query = query.with_for_update()
    user = (await session.execute(query)).scalar_one_or_none()
    if user is None:
        raise _not_found()
    role = await session.get(RoleRecord, user.role)
    if not can_manage(actor, user, role):
        # Same answer as "not found", so managers cannot probe other branches' staff.
        raise _not_found()
    return user


async def list_users(
    session: AsyncSession, actor: CurrentUser, f: UserFilter, page: int, size: int
) -> tuple[list[User], int]:
    query = select(User)
    if not actor.is_owner:
        # Staff sharing at least one branch with the manager.
        query = query.where(
            User.id.in_(
                select(UserBranch.user_id).where(UserBranch.branch_id.in_(actor.branch_ids or [UUID(int=0)]))
            )
        )
    if f.q:
        like = f"%{f.q.strip()}%"
        query = query.where(or_(User.name.ilike(like), User.phone.ilike(like)))
    if f.role:
        query = query.where(User.role == f.role)
    if f.branch_id:
        query = query.where(
            User.id.in_(select(UserBranch.user_id).where(UserBranch.branch_id == f.branch_id))
        )
    if f.is_active is not None:
        query = query.where(User.is_active.is_(f.is_active))
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = await session.execute(query.order_by(User.name, User.id).offset((page - 1) * size).limit(size))
    return list(rows.scalars()), int(total)


async def create_user(
    session: AsyncSession,
    actor: CurrentUser,
    *,
    name: str,
    phone: str,
    password: str,
    role: str,
    is_pharmacist: bool,
    locale: str,
    branch_ids: list[UUID],
    ip: str | None,
) -> User:
    role_rec = await _get_role(session, role)
    _check_assignable(actor, role_rec)
    phone = _phone(phone)
    await _check_phone_free(session, phone)
    _check_password(password)
    ids = await _check_branches(session, actor, role, branch_ids)

    user = User(
        name=name.strip(),
        phone=phone,
        password_hash=hash_password(password),
        role=role,
        is_pharmacist=is_pharmacist,
        locale=locale,
        created_by=actor.id,
        branches=[UserBranch(branch_id=b) for b in ids],
    )
    session.add(user)
    await session.flush()
    add_event(session, OutboxEvent, "user.created", user_event_payload(user))
    write_audit(
        session,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        branch_id=_primary_branch(user),
        after=user.safe_fields(),
        ip=ip,
        only_changes=False,
    )
    await session.commit()
    return user


async def update_user(
    session: AsyncSession,
    redis: Redis,
    actor: CurrentUser,
    user_id: UUID,
    changes: dict[str, object],
    ip: str | None,
) -> User:
    user = await get_manageable(session, actor, user_id, lock=True)
    before = user.safe_fields()
    sensitive = {"role", "branch_ids", "is_pharmacist"} & set(changes)
    if user.id == actor.id and sensitive:
        raise AppError(
            ErrorCode.CANNOT_CHANGE_SELF, "Ask another manager or the owner to change this", status_code=403
        )

    if "name" in changes:
        user.name = str(changes["name"]).strip()
    if "locale" in changes:
        user.locale = str(changes["locale"])
    if "phone" in changes:
        phone = _phone(str(changes["phone"]))
        await _check_phone_free(session, phone, except_id=user.id)
        user.phone = phone
    if "is_pharmacist" in changes:
        user.is_pharmacist = bool(changes["is_pharmacist"])

    new_role = str(changes.get("role", user.role))
    if new_role != user.role:
        role_rec = await _get_role(session, new_role)
        _check_assignable(actor, role_rec)
        if user.role == OWNER and user.is_active and await _active_owner_count(session) <= 1:
            raise AppError(ErrorCode.LAST_OWNER, "The last owner must stay owner", status_code=409)
        user.role = new_role

    if "branch_ids" in changes or new_role != before["role"]:
        requested = changes.get("branch_ids", user.branch_ids)
        ids = await _check_branches(session, actor, new_role, list(requested))  # type: ignore[arg-type]
        user.branches = [UserBranch(branch_id=b) for b in ids]

    await session.flush()
    after = user.safe_fields()
    if after == before:
        await session.commit()
        return user
    if {"role", "branch_ids", "is_pharmacist"} & {k for k in after if after[k] != before[k]}:
        await _end_sessions(session, redis, user.id)
    add_event(session, OutboxEvent, "user.updated", user_event_payload(user))
    write_audit(
        session,
        action="user.updated",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        branch_id=_primary_branch(user),
        before=before,
        after=after,
        ip=ip,
    )
    await session.commit()
    return user


async def set_active(
    session: AsyncSession,
    redis: Redis,
    actor: CurrentUser,
    user_id: UUID,
    active: bool,
    reason: str | None,
    ip: str | None,
) -> User:
    user = await get_manageable(session, actor, user_id, lock=True)
    if user.id == actor.id:
        raise AppError(ErrorCode.CANNOT_CHANGE_SELF, "You cannot deactivate yourself", status_code=403)
    if user.is_active == active:
        return user
    if not active and user.role == OWNER and await _active_owner_count(session) <= 1:
        raise AppError(ErrorCode.LAST_OWNER, "The last owner cannot be deactivated", status_code=409)
    user.is_active = active
    if not active:
        await _end_sessions(session, redis, user.id)
    action = "user.activated" if active else "user.deactivated"
    add_event(session, OutboxEvent, action, user_event_payload(user))
    write_audit(
        session,
        action=action,
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        branch_id=_primary_branch(user),
        before={"is_active": not active},
        after={"is_active": active, "reason": reason},
        ip=ip,
        only_changes=False,
    )
    await session.commit()
    return user


async def reset_password(
    session: AsyncSession, redis: Redis, actor: CurrentUser, user_id: UUID, new_password: str, ip: str | None
) -> None:
    user = await get_manageable(session, actor, user_id, lock=True)
    _check_password(new_password)
    user.password_hash = hash_password(new_password)
    user.failed_attempts = 0
    user.locked_until = None
    await _end_sessions(session, redis, user.id)
    write_audit(
        session,
        action="user.password_reset",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        branch_id=_primary_branch(user),
        ip=ip,
        only_changes=False,
    )
    await session.commit()


async def change_own_password(
    session: AsyncSession, redis: Redis, user_id: UUID, current: str, new: str, ip: str | None
) -> None:
    user = (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
    if not verify_password(user.password_hash, current):
        raise AppError(ErrorCode.INVALID_CREDENTIALS, "Current password is wrong", status_code=401)
    _check_password(new)
    user.password_hash = hash_password(new)
    await _end_sessions(session, redis, user.id)
    write_audit(
        session,
        action="user.password_changed",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        branch_id=_primary_branch(user),
        ip=ip,
        only_changes=False,
    )
    await session.commit()


async def set_own_pin(session: AsyncSession, user_id: UUID, password: str, pin: str, ip: str | None) -> None:
    """The PIN confirms controlled-drug dispensing and switches user on shared POS."""
    user = (await session.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
    if not verify_password(user.password_hash, password):
        raise AppError(ErrorCode.INVALID_CREDENTIALS, "Password is wrong", status_code=401)
    if not pin.isdigit() or len(pin) not in PIN_LENGTHS:
        raise AppError(ErrorCode.INVALID_PIN, "PIN must be 4 to 6 digits", status_code=422)
    user.pin_hash = hash_password(pin)
    write_audit(
        session,
        action="user.pin_set",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        branch_id=_primary_branch(user),
        ip=ip,
        only_changes=False,
    )
    await session.commit()


async def clear_pin(session: AsyncSession, actor: CurrentUser, user_id: UUID, ip: str | None) -> None:
    user = await get_manageable(session, actor, user_id, lock=True)
    user.pin_hash = None
    write_audit(
        session,
        action="user.pin_cleared",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        branch_id=_primary_branch(user),
        ip=ip,
        only_changes=False,
    )
    await session.commit()


async def reset_2fa(
    session: AsyncSession, redis: Redis, actor: CurrentUser, user_id: UUID, ip: str | None
) -> None:
    """For a lost phone: the user sets up 2FA again at the next login."""
    user = await get_manageable(session, actor, user_id, lock=True)
    if user.id == actor.id:
        raise AppError(ErrorCode.CANNOT_CHANGE_SELF, "Ask another owner to reset your 2FA", status_code=403)
    user.totp_secret_enc = None
    user.totp_enabled = False
    user.totp_last_step = None
    await _end_sessions(session, redis, user.id)
    write_audit(
        session,
        action="user.2fa_reset",
        entity_type="user",
        entity_id=user.id,
        actor=actor,
        branch_id=_primary_branch(user),
        before={"totp_enabled": True},
        after={"totp_enabled": False},
        ip=ip,
        only_changes=False,
    )
    await session.commit()
