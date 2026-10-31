"""Outbox replay: /internal/v1/outbox pages the outbox by seq for allowed services;
the relay never deletes rows (it only marks them published)."""

import httpx
import pytest
from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import DeclarativeBase

from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.config import BaseServiceSettings
from pharmacy_shared.db import Database
from pharmacy_shared.errors import AppError
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.outbox import OutboxMixin, add_event
from pharmacy_shared.outbox_relay import relay_once
from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database

TOKEN = "t" * 40


class FakePublisher:
    async def publish(self, event_type: str, payload: dict, message_id: object) -> None:
        pass


class _Base(DeclarativeBase):
    pass


class OutboxEvent(OutboxMixin, _Base):
    __tablename__ = "outbox"


@pytest.fixture
async def app():
    url = await recreate_database("test_shared_replay")
    database = Database(url)
    async with database.engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    async with database.sessionmaker() as session, session.begin():
        for i in range(5):
            add_event(session, OutboxEvent, f"thing.n{i}", {"n": i})
    settings = BaseServiceSettings(_env_file=None, service_name="sales", api_prefix="/api/sales/v1",
                                   redis_url=TEST_REDIS_URL, service_token=TOKEN, outbox_relay_enabled=False,
                                   database_url=url)  # fmt: skip
    yield create_service_app(settings, database, APIRouter(), "test", outbox_model=OutboxEvent)
    await database.dispose()


def client(app, name: str = "reports") -> InternalClient:  # noqa: ANN001
    return InternalClient("http://sales:8000", name, TOKEN, transport=httpx.ASGITransport(app=app))


async def test_pages_by_seq_after_the_relay_published_them(app) -> None:
    db: Database = app.state.db
    assert await relay_once(db.sessionmaker, OutboxEvent, FakePublisher(), batch_size=100) == 5
    async with db.sessionmaker() as session:  # published, never deleted
        assert (await session.execute(select(func.count()).select_from(OutboxEvent))).scalar_one() == 5
    first = await client(app).get("/outbox", {"after_seq": 0, "limit": 3})
    assert [x["payload"]["n"] for x in first["items"]] == [0, 1, 2] and first["more"]
    rest = await client(app).get("/outbox", {"after_seq": first["next_after_seq"], "limit": 3})
    assert [x["payload"]["n"] for x in rest["items"]] == [3, 4] and not rest["more"]
    assert rest["items"][0]["event_type"] == "thing.n3" and rest["items"][0]["created_at"]


async def test_401_without_the_service_token_and_403_for_other_services(app) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x") as c:
        assert (await c.get("/internal/v1/outbox")).status_code == 401
        r = await c.get("/internal/v1/outbox", headers={"X-Service-Token": "wrong" * 8, "X-Service-Name": "reports"})
        assert r.status_code == 401
    with pytest.raises(AppError) as exc:
        await client(app, "inventory").get("/outbox")
    assert exc.value.status_code == 403
