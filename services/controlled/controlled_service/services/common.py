"""Helpers shared by the controlled service modules."""

import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import OutboxEvent

SERVICE = "controlled"


def clean(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or "")).strip()


def not_found(what: str) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found", status_code=404)


def audit(
    session: AsyncSession, actor: CurrentUser | None, action: str, entity_type: str, entity_id: Any,
    *, branch_id: UUID | None = None, before: dict | None = None, after: dict | None = None,
) -> None:  # fmt: skip
    record_audit(session, OutboxEvent, service=SERVICE, action=action, entity_type=entity_type,
                 entity_id=entity_id, actor=actor, branch_id=branch_id, before=before, after=after)  # fmt: skip
