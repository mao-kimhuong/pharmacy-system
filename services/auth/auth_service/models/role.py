from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import Base


class RoleRecord(Base):
    """A role on the Role screen. Built-in roles cannot be removed; the owner
    role always has every permission and cannot be edited."""

    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(255), default="", server_default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    grants: Mapped[list["RolePermission"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", back_populates="role"
    )

    @property
    def permission_keys(self) -> list[str]:
        return sorted(g.permission_key for g in self.grants)


class Permission(Base):
    """Copied from auth_service.permissions.CATALOG at start-up."""

    __tablename__ = "permissions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    group: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_key: Mapped[str] = mapped_column(
        ForeignKey("roles.key", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    permission_key: Mapped[str] = mapped_column(
        ForeignKey("permissions.key", ondelete="CASCADE"), primary_key=True
    )

    role: Mapped[RoleRecord] = relationship(back_populates="grants")
