"""Documents printed from copies kept from events (purchase orders, invoices).

- upsert_versioned: stores an event payload; an older or equal version is ignored.
- wait_for: right after a sale or a PO is saved its event may still be on the
  way. Look again every 0.25 s for up to `wait_seconds` (5), then
  DOCUMENT_NOT_READY (409, try again). Other branches' documents: 404.
"""

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode


async def upsert_versioned(session: AsyncSession, model: type, values: dict[str, Any]) -> bool:
    stored = (
        await session.execute(select(model.version).where(model.id == values["id"]).with_for_update())
    ).scalar_one_or_none()
    if stored is not None and stored >= values["version"]:
        return False
    await session.execute(insert(model).values(**values).on_conflict_do_update(
        index_elements=[model.id], set_={k: v for k, v in values.items() if k != "id"}))  # fmt: skip
    return True


async def wait_for(
    session: AsyncSession, model: type, doc_id: UUID, actor: CurrentUser, wait_seconds: float, what: str
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        row = (await session.execute(select(model.branch_id, model.data).where(model.id == doc_id))).first()
        await session.rollback()  # end the read, so the next look sees newly committed copies
        if row is not None:
            if not actor.can_access_branch(row.branch_id):
                raise AppError(ErrorCode.NOT_FOUND, f"{what.capitalize()} not found", status_code=404)
            return row.data
        if loop.time() >= deadline:
            raise AppError(ErrorCode.DOCUMENT_NOT_READY,
                           f"This {what} has not reached the document service yet; try again in a moment",
                           status_code=409)  # fmt: skip
        await asyncio.sleep(0.25)
