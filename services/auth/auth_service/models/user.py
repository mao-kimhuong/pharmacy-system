from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base


class Role(StrEnum):
    """The built-in roles. More roles can be created on the Role screen."""

    OWNER = "owner"
    BRANCH_MANAGER = "branch_manager"
    PHARMACIST = "pharmacist"
    CASHIER = "cashier"


ROLES = tuple(r.value for r in Role)


class User(IdMixin, TimestampMixin, Base):
    """Staff account. Never deleted: deactivate with is_active = false."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("locale IN ('km', 'en')", name="ck_users_locale"),)

    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(ForeignKey("roles.key", onupdate="CASCADE"), index=True)
    is_pharmacist: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    locale: Mapped[str] = mapped_column(String(2), default="km", server_default="km")
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    # Two-factor login (authenticator app). The secret is stored encrypted.
    totp_secret_enc: Mapped[str | None] = mapped_column(String(255))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)  # blocks re-use of a code
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    branches: Mapped[list["UserBranch"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def branch_ids(self) -> list[UUID]:
        return sorted((b.branch_id for b in self.branches), key=str)

    def safe_fields(self) -> dict[str, object]:
        """Fields that may appear in the User Log (never secrets)."""
        return {
            "name": self.name,
            "phone": self.phone,
            "role": self.role,
            "is_pharmacist": self.is_pharmacist,
            "is_active": self.is_active,
            "locale": self.locale,
            "branch_ids": [str(b) for b in self.branch_ids],
            "totp_enabled": self.totp_enabled,
        }


class UserBranch(Base):
    """Which branches a user may work in. Branches live in the branch service,
    so branch_id is not a foreign key here."""

    __tablename__ = "user_branches"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)

    user: Mapped[User] = relationship(back_populates="branches")
