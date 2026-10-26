"""Settings → Role. The owner role always has every permission and cannot be
edited. Built-in roles cannot be removed. Permission changes reach users at
their next token refresh (within 15 minutes)."""

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import RolePermission, RoleRecord, User
from ..permissions import KEYS, OWNER
from .audit import write_audit

_KEY = re.compile(r"^[a-z][a-z0-9_]{2,31}$")


def _check_permissions(permissions: list[str]) -> list[str]:
    unknown = sorted(set(permissions) - KEYS)
    if unknown:
        raise AppError(
            ErrorCode.UNKNOWN_PERMISSION,
            "Unknown permission",
            status_code=422,
            details={"permissions": unknown},
        )
    return sorted(set(permissions))


async def get_role(session: AsyncSession, key: str) -> RoleRecord:
    role = await session.get(RoleRecord, key)
    if role is None:
        raise AppError(ErrorCode.NOT_FOUND, "Role not found", status_code=404)
    return role


async def list_roles(session: AsyncSession) -> list[tuple[RoleRecord, int]]:
    counts = dict(
        (
            await session.execute(
                select(User.role, func.count(User.id)).where(User.is_active.is_(True)).group_by(User.role)
            )
        ).all()
    )
    roles = (
        await session.execute(select(RoleRecord).order_by(RoleRecord.is_system.desc(), RoleRecord.name))
    ).scalars()
    return [(r, int(counts.get(r.key, 0))) for r in roles]


def _snapshot(role: RoleRecord, permissions: list[str]) -> dict[str, object]:
    return {
        "name": role.name,
        "description": role.description,
        "permissions": permissions,
        "is_active": role.is_active,
    }


async def create_role(
    session: AsyncSession,
    actor: CurrentUser,
    *,
    key: str,
    name: str,
    description: str,
    permissions: list[str],
    ip: str | None,
) -> RoleRecord:
    if not _KEY.match(key):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Key: 3-32 lowercase letters, digits or _, starting with a letter",
            status_code=422,
        )
    if await session.get(RoleRecord, key) is not None:
        raise AppError(ErrorCode.DUPLICATE_CODE, "A role with this key already exists", status_code=409)
    perms = _check_permissions(permissions)
    role = RoleRecord(
        key=key,
        name=name.strip(),
        description=description.strip(),
        is_system=False,
        grants=[RolePermission(permission_key=p) for p in perms],
    )
    session.add(role)
    write_audit(
        session,
        action="role.created",
        entity_type="role",
        entity_id=key,
        actor=actor,
        after=_snapshot(role, perms),
        ip=ip,
        only_changes=False,
    )
    await session.commit()
    return role


async def update_role(
    session: AsyncSession,
    actor: CurrentUser,
    key: str,
    *,
    name: str | None = None,
    description: str | None = None,
    permissions: list[str] | None = None,
    ip: str | None = None,
) -> RoleRecord:
    role = await get_role(session, key)
    if role.key == OWNER:
        raise AppError(
            ErrorCode.ROLE_NOT_EDITABLE, "The owner role always has every permission", status_code=409
        )
    before = _snapshot(role, role.permission_keys)
    if name is not None:
        role.name = name.strip()
    if description is not None:
        role.description = description.strip()
    if permissions is not None:
        perms = _check_permissions(permissions)
        role.grants = [RolePermission(permission_key=p) for p in perms]
    await session.flush()
    after = _snapshot(role, sorted(g.permission_key for g in role.grants))
    write_audit(
        session,
        action="role.updated",
        entity_type="role",
        entity_id=key,
        actor=actor,
        before=before,
        after=after,
        ip=ip,
    )
    await session.commit()
    return role


async def set_role_active(
    session: AsyncSession, actor: CurrentUser, key: str, active: bool, ip: str | None
) -> RoleRecord:
    role = await get_role(session, key)
    if role.is_system:
        raise AppError(ErrorCode.ROLE_NOT_EDITABLE, "Built-in roles cannot be removed", status_code=409)
    if not active:
        in_use = await session.execute(
            select(func.count(User.id)).where(User.role == key, User.is_active.is_(True))
        )
        count = int(in_use.scalar_one())
        if count:
            raise AppError(
                ErrorCode.ROLE_IN_USE,
                "Give these staff another role first",
                status_code=409,
                details={"users": count},
            )
    role.is_active = active
    write_audit(
        session,
        action="role.activated" if active else "role.deactivated",
        entity_type="role",
        entity_id=key,
        actor=actor,
        before={"is_active": not active},
        after={"is_active": active},
        ip=ip,
        only_changes=False,
    )
    await session.commit()
    return role
