"""Current user, read from the headers Traefik ForwardAuth injects.

Traefik first strips any identity headers sent by the client
(strip-identity-headers middleware), then asks the auth service's /verify
endpoint, which sets them from the validated token:

    X-User-Id, X-Role, X-Branch-Ids, X-Is-Pharmacist, X-Permissions

Services never trust role, user, branch or permission values from the body.
"""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header

from .errors import AppError, ErrorCode

USER_ID_HEADER = "x-user-id"
ROLE_HEADER = "x-role"
BRANCH_IDS_HEADER = "x-branch-ids"
IS_PHARMACIST_HEADER = "x-is-pharmacist"
PERMISSIONS_HEADER = "x-permissions"

ALL_PERMISSIONS = "*"  # the owner role


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    role: str
    branch_ids: frozenset[UUID]
    is_pharmacist: bool
    permissions: frozenset[str] = frozenset()

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def has(self, permission: str) -> bool:
        return ALL_PERMISSIONS in self.permissions or permission in self.permissions

    def has_any(self, *permissions: str) -> bool:
        return any(self.has(p) for p in permissions)

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "You do not have permission to do this",
                status_code=403,
                details={"permission": permission},
            )

    def can_access_branch(self, branch_id: UUID) -> bool:
        return self.is_owner or branch_id in self.branch_ids

    def require_branch(self, branch_id: UUID) -> None:
        if not self.can_access_branch(branch_id):
            raise AppError(ErrorCode.BRANCH_FORBIDDEN, "No access to this branch", status_code=403)


def _not_authenticated() -> AppError:
    return AppError(ErrorCode.NOT_AUTHENTICATED, "Not authenticated", status_code=401)


def current_user(
    x_user_id: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
    x_branch_ids: str | None = Header(default=None),
    x_is_pharmacist: str | None = Header(default=None),
    x_permissions: str | None = Header(default=None),
) -> CurrentUser:
    if not x_user_id or not x_role:
        raise _not_authenticated()
    try:
        user_id = UUID(x_user_id)
        branches = frozenset(UUID(b) for b in (x_branch_ids or "").split(",") if b)
    except ValueError as exc:
        raise _not_authenticated() from exc
    return CurrentUser(
        id=user_id,
        role=x_role,
        branch_ids=branches,
        is_pharmacist=(x_is_pharmacist or "").lower() == "true",
        permissions=frozenset(p for p in (x_permissions or "").split(",") if p),
    )


def requires(permission: str):  # noqa: ANN201 - returns a FastAPI dependency
    """Route dependency: `user: CurrentUser = Depends(requires("settings.users"))`."""

    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        user.require(permission)
        return user

    return dependency


def requires_any(*permissions: str):  # noqa: ANN201 - returns a FastAPI dependency
    """Route dependency: allowed with any one of the permissions."""

    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if not user.has_any(*permissions):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "You do not have permission to do this",
                status_code=403,
                details={"permission": " or ".join(permissions)},
            )
        return user

    return dependency
