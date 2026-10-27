from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ImportRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    row_no: int
    sku: str
    action: str | None
    data: dict[str, Any]
    errors: list[dict[str, Any]]


class ImportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_name: str
    status: str  # validated / has_errors / committed
    total_rows: int
    error_rows: int
    new_categories: list[str]
    new_brands: list[str]
    created_count: int
    updated_count: int
    skipped_skus: list[str]
    created_at: datetime
    committed_at: datetime | None


class ImportDetail(ImportSummary):
    rows: list[ImportRowOut]
    rows_total: int
    page: int
    size: int


class ImportPage(BaseModel):
    items: list[ImportSummary]
    total: int
    page: int
    size: int


class ImportCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Create the categories / brands listed in new_categories / new_brands.
    create_missing: bool = False
    # Import the valid products and skip every SKU that has an error.
    skip_invalid: bool = False
