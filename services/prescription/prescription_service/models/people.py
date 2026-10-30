from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base


class Patient(IdMixin, TimestampMixin, Base):
    """Never deleted: deactivate. Visible at the home branch and at every branch
    linked in patient_branches (a branch that wrote an Rx, or found the patient
    by exact phone)."""

    __tablename__ = "patients"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint("sex IN ('female', 'male', 'other')", name="ck_patients_sex"),)

    name_km: Mapped[str] = mapped_column(String(160), default="", server_default="")
    name_en: Mapped[str] = mapped_column(String(160), default="", server_default="")
    sex: Mapped[str] = mapped_column(String(8))
    dob: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(20), default="", server_default="", index=True)  # normalized
    customer_id: Mapped[UUID | None] = mapped_column(Uuid)
    home_branch_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    chronic_conditions: Mapped[str] = mapped_column(Text, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    allergies: Mapped[list["PatientAllergy"]] = relationship(
        lazy="selectin", order_by="PatientAllergy.created_at"
    )
    branches: Mapped[list["PatientBranch"]] = relationship(lazy="selectin")

    @property
    def branch_ids(self) -> list[UUID]:
        return [b.branch_id for b in self.branches]

    @property
    def active_allergies(self) -> list["PatientAllergy"]:
        return [a for a in self.allergies if a.is_active]

    def safe_fields(self) -> dict[str, Any]:
        return {
            "name_km": self.name_km, "name_en": self.name_en, "sex": self.sex,
            "dob": self.dob.isoformat() if self.dob else None, "phone": self.phone,
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "chronic_conditions": self.chronic_conditions, "notes": self.notes, "is_active": self.is_active,
        }  # fmt: skip


class PatientAllergy(IdMixin, Base):
    """An allergy to an active ingredient or a drug class (names as in the catalog).
    Not deleted: deactivated with a reason."""

    __tablename__ = "patient_allergies"
    __table_args__ = (CheckConstraint("kind IN ('ingredient', 'class')", name="ck_allergies_kind"),)

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    value: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(String(255), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PatientBranch(Base):
    __tablename__ = "patient_branches"

    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"), primary_key=True)
    branch_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Doctor(IdMixin, TimestampMixin, Base):
    """Never deleted: deactivate. Doctors are shared by all branches."""

    __tablename__ = "doctors"

    name: Mapped[str] = mapped_column(String(160))
    licence_no: Mapped[str] = mapped_column(String(60), unique=True)
    specialty: Mapped[str] = mapped_column(String(120), default="", server_default="")
    clinic: Mapped[str] = mapped_column(String(160), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(20), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(Uuid)

    def safe_fields(self) -> dict[str, Any]:
        return {"name": self.name, "licence_no": self.licence_no, "specialty": self.specialty,
                "clinic": self.clinic, "phone": self.phone, "is_active": self.is_active}  # fmt: skip
