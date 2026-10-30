"""SQLAlchemy models of the auth service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.consumer import ProcessedMessageMixin
from pharmacy_shared.outbox import OutboxMixin

from .audit import AuditLog
from .base import Base
from .known_branch import KnownBranch
from .refresh_token import RefreshToken
from .role import AppliedGrant, Permission, RolePermission, RoleRecord
from .user import ROLES, Role, User, UserBranch


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


class ProcessedMessage(ProcessedMessageMixin, Base):
    __tablename__ = "processed_messages"


__all__ = [
    "AppliedGrant",
    "AuditLog",
    "Base",
    "KnownBranch",
    "OutboxEvent",
    "Permission",
    "ProcessedMessage",
    "ROLES",
    "RefreshToken",
    "Role",
    "RolePermission",
    "RoleRecord",
    "User",
    "UserBranch",
]
