from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from pharmacy_shared.db import IdMixin, TimestampMixin

from .base import Base

IMPORT_STATUSES = ("validated", "has_errors", "committed")


class ProductImport(IdMixin, TimestampMixin, Base):
    """An uploaded Excel file, validated row by row. Nothing reaches the
    medicines table until it is committed. The file itself is not kept."""

    __tablename__ = "imports"

    file_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    # Category / brand names in the file that do not exist yet. Created on
    # commit only with create_missing=true.
    new_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    new_brands: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_skus: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    committed_by: Mapped[UUID | None] = mapped_column(Uuid)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRow(IdMixin, Base):
    __tablename__ = "import_rows"

    import_id: Mapped[UUID] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"), index=True)
    row_no: Mapped[int] = mapped_column(Integer)  # Excel row number, as the user sees it
    sku: Mapped[str] = mapped_column(String(40), default="")
    action: Mapped[str | None] = mapped_column(String(10))  # create / update
    # Cell values as text, keyed by column name
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    # [{"field": "barcode", "code": "DUPLICATE_BARCODE", "message": "..."}]
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
