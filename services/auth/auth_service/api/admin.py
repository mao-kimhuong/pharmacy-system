"""Settings screens: User, Role, User Log."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires

from ..db import db
from ..models import RoleRecord, User
from ..permissions import CATALOG, OWNER
from ..schemas.admin import (
    AuditOut,
    AuditPage,
    PermissionOut,
    ReasonRequest,
    ResetPasswordRequest,
    ResetTwoFactorRequest,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserOut,
    UserPage,
    UserUpdate,
)
from ..services import audit as audit_service
from ..services import roles as roles_service
from ..services import users as users_service
from .auth import client_info, get_redis

router = APIRouter()

manage_users = requires("settings.users")
manage_roles = requires("settings.roles")
read_audit = requires("settings.audit_log")


# ---------------------------------------------------------------- users


@router.get("/users", response_model=UserPage, tags=["users"])
async def list_users(
    q: str | None = Query(default=None, max_length=60, description="name or phone"),
    role: str | None = Query(default=None, max_length=32),
    branch_id: UUID | None = None,
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
) -> UserPage:
    items, total = await users_service.list_users(
        session, actor, users_service.UserFilter(q, role, branch_id, is_active), page, size
    )
    return UserPage(items=[UserOut.model_validate(u) for u in items], total=total, page=page, size=size)


@router.post("/users", response_model=UserOut, status_code=201, tags=["users"])
async def create_user(
    body: UserCreate,
    request: Request,
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
) -> User:
    return await users_service.create_user(session, actor, **body.model_dump(), ip=client_info(request).ip)


@router.get("/users/{user_id}", response_model=UserOut, tags=["users"])
async def get_user(
    user_id: UUID, actor: CurrentUser = Depends(manage_users), session: AsyncSession = Depends(db.session)
) -> User:
    return await users_service.get_manageable(session, actor, user_id)


@router.patch("/users/{user_id}", response_model=UserOut, tags=["users"])
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    request: Request,
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
) -> User:
    """Changing role, branches or the pharmacist flag logs the user out everywhere."""
    changes = body.model_dump(exclude_unset=True)
    return await users_service.update_user(session, redis, actor, user_id, changes, client_info(request).ip)


@router.post("/users/{user_id}/deactivate", response_model=UserOut, tags=["users"])
async def deactivate_user(
    user_id: UUID,
    body: ReasonRequest,
    request: Request,
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
) -> User:
    """The user is logged out everywhere at once and cannot log in."""
    return await users_service.set_active(
        session, redis, actor, user_id, False, body.reason, client_info(request).ip
    )


@router.post("/users/{user_id}/activate", response_model=UserOut, tags=["users"])
async def activate_user(
    user_id: UUID,
    request: Request,
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
) -> User:
    return await users_service.set_active(session, redis, actor, user_id, True, None, client_info(request).ip)


@router.post("/users/{user_id}/reset-password", status_code=204, tags=["users"])
async def reset_password(
    user_id: UUID,
    body: ResetPasswordRequest,
    request: Request,
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Sets a new password, unlocks the account and ends all its sessions."""
    await users_service.reset_password(
        session, redis, actor, user_id, body.new_password, client_info(request).ip
    )
    return Response(status_code=204)


@router.delete("/users/{user_id}/pin", status_code=204, tags=["users"])
async def clear_pin(
    user_id: UUID,
    request: Request,
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
) -> Response:
    """Remove a forgotten PIN; the user sets a new one on their profile."""
    await users_service.clear_pin(session, actor, user_id, client_info(request).ip)
    return Response(status_code=204)


@router.post("/users/{user_id}/2fa/reset", status_code=204, tags=["users"])
async def reset_2fa(
    user_id: UUID,
    body: ResetTwoFactorRequest,
    request: Request,
    actor: CurrentUser = Depends(manage_users),
    session: AsyncSession = Depends(db.session),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Lost phone (owner only, `pin_token` from /pin/verify, action auth.mfa_reset): turns 2FA off and ends the
    user's sessions; they set it up again at the next login if their role needs it."""
    await users_service.reset_2fa(session, redis, actor, user_id, body.pin_token, client_info(request).ip)
    return Response(status_code=204)


# ---------------------------------------------------------------- roles


def _role_out(role: RoleRecord, users: int = 0) -> RoleOut:
    return RoleOut(
        key=role.key,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        is_active=role.is_active,
        permissions=role.permission_keys,
        all_permissions=role.key == OWNER,
        active_users=users,
    )


@router.get("/permissions", response_model=list[PermissionOut], tags=["roles"])
async def list_permissions(_: CurrentUser = Depends(manage_roles)) -> list[PermissionOut]:
    """Every permission, grouped by menu group, for the role checklist."""
    return [PermissionOut(key=p.key, group=p.group, label=p.label) for p in CATALOG]


@router.get("/roles", response_model=list[RoleOut], tags=["roles"])
async def list_roles(
    _: CurrentUser = Depends(requires("settings.users")), session: AsyncSession = Depends(db.session)
) -> list[RoleOut]:
    """Also used by the User screen to pick a role, so `settings.users` is enough."""
    return [_role_out(r, n) for r, n in await roles_service.list_roles(session)]


@router.post("/roles", response_model=RoleOut, status_code=201, tags=["roles"])
async def create_role(
    body: RoleCreate,
    request: Request,
    actor: CurrentUser = Depends(manage_roles),
    session: AsyncSession = Depends(db.session),
) -> RoleOut:
    role = await roles_service.create_role(session, actor, **body.model_dump(), ip=client_info(request).ip)
    return _role_out(role)


@router.patch("/roles/{key}", response_model=RoleOut, tags=["roles"])
async def update_role(
    key: str,
    body: RoleUpdate,
    request: Request,
    actor: CurrentUser = Depends(manage_roles),
    session: AsyncSession = Depends(db.session),
) -> RoleOut:
    """Staff get the new permissions at their next token refresh (within 15 minutes)."""
    role = await roles_service.update_role(
        session, actor, key, **body.model_dump(exclude_unset=True), ip=client_info(request).ip
    )
    return _role_out(role)


@router.post("/roles/{key}/deactivate", response_model=RoleOut, tags=["roles"])
async def deactivate_role(
    key: str,
    request: Request,
    actor: CurrentUser = Depends(manage_roles),
    session: AsyncSession = Depends(db.session),
) -> RoleOut:
    return _role_out(await roles_service.set_role_active(session, actor, key, False, client_info(request).ip))


@router.post("/roles/{key}/activate", response_model=RoleOut, tags=["roles"])
async def activate_role(
    key: str,
    request: Request,
    actor: CurrentUser = Depends(manage_roles),
    session: AsyncSession = Depends(db.session),
) -> RoleOut:
    return _role_out(await roles_service.set_role_active(session, actor, key, True, client_info(request).ip))


# ---------------------------------------------------------------- user log


@router.get("/audit-logs", response_model=AuditPage, tags=["user log"])
async def list_audit_logs(
    actor_id: UUID | None = None,
    branch_id: UUID | None = None,
    action: str | None = Query(default=None, max_length=64),
    entity_type: str | None = Query(default=None, max_length=40),
    entity_id: str | None = Query(default=None, max_length=64),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    actor: CurrentUser = Depends(read_audit),
    session: AsyncSession = Depends(db.session),
) -> AuditPage:
    """Newest first. Branch managers see entries of their own branches only."""
    items, total = await audit_service.list_audit(
        session,
        actor,
        page=page,
        size=size,
        actor_id=actor_id,
        branch_id=branch_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
    )
    return AuditPage(items=[AuditOut.model_validate(a) for a in items], total=total, page=page, size=size)
