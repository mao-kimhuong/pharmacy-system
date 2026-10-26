from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase

from pharmacy_shared.db import Database
from pharmacy_shared.outbox import OutboxMixin, add_event
from pharmacy_shared.outbox_relay import relay_once
from pharmacy_shared.testing import recreate_database


class _Base(DeclarativeBase):
    pass


class OutboxEvent(OutboxMixin, _Base):
    __tablename__ = "outbox"


class FakePublisher:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, dict[str, Any], UUID]] = []
        self.fail = fail

    async def publish(self, event_type: str, payload: dict[str, Any], message_id: UUID) -> None:
        if self.fail:
            raise ConnectionError("rabbitmq down")
        self.sent.append((event_type, payload, message_id))


@pytest.fixture
async def db():
    database = Database(await recreate_database("test_shared_outbox"))
    async with database.engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    yield database
    await database.dispose()


async def add_events(db: Database, *types: str) -> None:
    async with db.sessionmaker() as session, session.begin():
        for t in types:
            add_event(session, OutboxEvent, t, {"type": t})


async def test_publishes_unpublished_events_in_order_and_marks_them(db: Database) -> None:
    await add_events(db, "a.created", "b.created", "c.created")
    publisher = FakePublisher()

    assert await relay_once(db.sessionmaker, OutboxEvent, publisher) == 3
    assert [t for t, _, _ in publisher.sent] == ["a.created", "b.created", "c.created"]

    async with db.sessionmaker() as session:
        rows = (await session.execute(select(OutboxEvent))).scalars().all()
    assert all(r.published_at is not None for r in rows)
    assert {r.id for r in rows} == {mid for _, _, mid in publisher.sent}

    # nothing left to send
    assert await relay_once(db.sessionmaker, OutboxEvent, publisher) == 0


async def test_batch_size_limits_one_run(db: Database) -> None:
    await add_events(db, "a", "b", "c")
    publisher = FakePublisher()
    assert await relay_once(db.sessionmaker, OutboxEvent, publisher, batch_size=2) == 2
    assert await relay_once(db.sessionmaker, OutboxEvent, publisher, batch_size=2) == 1


async def test_failed_publish_leaves_events_unpublished(db: Database) -> None:
    await add_events(db, "a.created")
    with pytest.raises(ConnectionError):
        await relay_once(db.sessionmaker, OutboxEvent, FakePublisher(fail=True))

    async with db.sessionmaker() as session:
        row = (await session.execute(select(OutboxEvent))).scalar_one()
    assert row.published_at is None

    publisher = FakePublisher()
    assert await relay_once(db.sessionmaker, OutboxEvent, publisher) == 1
