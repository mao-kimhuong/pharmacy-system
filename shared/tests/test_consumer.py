from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Integer, String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pharmacy_shared.consumer import ProcessedMessageMixin, process_message
from pharmacy_shared.db import Database
from pharmacy_shared.testing import recreate_database


class _Base(DeclarativeBase):
    pass


class ProcessedMessage(ProcessedMessageMixin, _Base):
    __tablename__ = "processed_messages"


class Counter(_Base):
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


@pytest.fixture
async def db():
    database = Database(await recreate_database("test_shared_consumer"))
    async with database.engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    async with database.sessionmaker() as session, session.begin():
        session.add(Counter(name="seen", value=0))
    yield database
    await database.dispose()


async def count_handler(session, event_type: str, payload: dict[str, Any], message_id: UUID) -> None:
    row = await session.get(Counter, "seen")
    row.value += payload["add"]


async def failing_handler(session, event_type: str, payload: dict[str, Any], message_id: UUID) -> None:
    row = await session.get(Counter, "seen")
    row.value += 100
    raise RuntimeError("handler broke")


async def counter(db: Database) -> int:
    async with db.sessionmaker() as session:
        return (await session.execute(select(Counter.value))).scalar_one()


async def test_same_message_is_processed_once(db: Database) -> None:
    mid = uuid4()
    assert await process_message(db, ProcessedMessage, count_handler, mid, "x.happened", {"add": 1})
    assert not await process_message(db, ProcessedMessage, count_handler, mid, "x.happened", {"add": 1})
    assert await counter(db) == 1


async def test_different_messages_are_all_processed(db: Database) -> None:
    for _ in range(3):
        await process_message(db, ProcessedMessage, count_handler, uuid4(), "x.happened", {"add": 2})
    assert await counter(db) == 6


async def test_failed_handler_changes_nothing_and_can_be_retried(db: Database) -> None:
    mid = uuid4()
    with pytest.raises(RuntimeError):
        await process_message(db, ProcessedMessage, failing_handler, mid, "x.happened", {})
    assert await counter(db) == 0
    # not marked as processed, so a retry runs
    assert await process_message(db, ProcessedMessage, count_handler, mid, "x.happened", {"add": 1})
    assert await counter(db) == 1
