import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.orm import DeclarativeBase

from pharmacy_shared.db import Database
from pharmacy_shared.numbering import DocSequenceMixin, next_number
from pharmacy_shared.testing import recreate_database
from pharmacy_shared.visibility import drop_fields


class _Base(DeclarativeBase):
    pass


class DocSequence(DocSequenceMixin, _Base):
    __tablename__ = "doc_sequences"


@pytest.fixture
async def db():
    database = Database(await recreate_database("test_shared_numbering"))
    async with database.engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    yield database
    await database.dispose()


async def test_numbers_have_no_gaps_under_concurrency_and_after_a_rollback(db) -> None:
    branch = uuid4()

    async def take(fail: bool = False) -> str | None:
        async with db.sessionmaker() as session:
            number = await next_number(session, DocSequence, branch, "PP1", "PO", 2026)
            await asyncio.sleep(0.01)
            if fail:
                await session.rollback()
                return None
            await session.commit()
            return number

    results = await asyncio.gather(*[take(fail=(i % 5 == 0)) for i in range(20)])
    numbers = sorted(n for n in results if n)
    assert numbers == [f"PP1-PO-2026-{i:06d}" for i in range(1, 17)]


async def test_each_branch_type_and_year_counts_separately(db) -> None:
    a, b = uuid4(), uuid4()
    async with db.sessionmaker() as session:
        assert await next_number(session, DocSequence, a, "PP1", "PO", 2026) == "PP1-PO-2026-000001"
        assert await next_number(session, DocSequence, a, "PP1", "GRN", 2026) == "PP1-GRN-2026-000001"
        assert await next_number(session, DocSequence, b, "PP2", "PO", 2026) == "PP2-PO-2026-000001"
        assert await next_number(session, DocSequence, a, "PP1", "PO", 2027) == "PP1-PO-2027-000001"
        assert await next_number(session, DocSequence, a, "PP1", "PO", 2026) == "PP1-PO-2026-000002"
        await session.commit()


def test_drop_fields_removes_keys_at_any_depth() -> None:
    data = {"id": 1, "unit_cost": "2", "lines": [{"qty": 1, "unit_cost": "2", "x": {"line_total": 3}}]}
    assert drop_fields(data, {"unit_cost", "line_total"}) == {"id": 1, "lines": [{"qty": 1, "x": {}}]}
