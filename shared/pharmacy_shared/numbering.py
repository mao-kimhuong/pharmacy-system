"""Document numbers per branch and year without gaps: PP1-PO-2026-000001.

Each service that numbers documents has a `doc_sequences` table:

    class DocSequence(DocSequenceMixin, Base):
        __tablename__ = "doc_sequences"

`next_number` increments the counter with INSERT ... ON CONFLICT DO UPDATE
... RETURNING in the caller's transaction. The updated row stays locked until
that transaction ends, so two tills numbering at once wait for each other, and
a transaction that fails rolls the counter back: no gaps, no duplicates.
Call it as late as possible (right before commit) to keep the lock short.
"""

from uuid import UUID

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import clock


class DocSequenceMixin:
    branch_id: Mapped[UUID] = mapped_column(primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(8), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_no: Mapped[int] = mapped_column(Integer)


async def next_number(
    session: AsyncSession,
    model: type,
    branch_id: UUID,
    branch_code: str,
    doc_type: str,
    year: int | None = None,
) -> str:
    year = year or clock.today().year
    stmt = (
        insert(model)
        .values(branch_id=branch_id, doc_type=doc_type, year=year, last_no=1)
        .on_conflict_do_update(
            index_elements=[model.branch_id, model.doc_type, model.year], set_={"last_no": model.last_no + 1}
        )
        .returning(model.last_no)
    )
    number = (await session.execute(stmt)).scalar_one()
    return f"{branch_code}-{doc_type}-{year}-{number:06d}"
