"""Notification tests: real Postgres + Redis; Telegram is a fake (httpx.MockTransport)."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_notification"
os.environ.update(DATABASE_URL=test_database_url(TEST_DB), REDIS_URL=TEST_REDIS_URL, OUTBOX_RELAY_ENABLED="false",
                  EVENT_CONSUMER_ENABLED="false", JOBS_ENABLED="false", TELEGRAM_BOT_TOKEN="")  # fmt: skip

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from notification_service.db import db  # noqa: E402
from notification_service.main import app  # noqa: E402
from notification_service.models import Base, Message, ProcessedMessage  # noqa: E402
from notification_service.services.events import handle_event  # noqa: E402
from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/notifications/v1"
TODAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)  # 20:00 in Phnom Penh
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")
PP2 = UUID("00000000-0000-0000-0000-0000000000a2")
TOKEN = "123456:TEST-TOKEN"


class FakeTelegram:
    """Answers like the Bot API; `replies` is a queue of (status, body), else 200 ok."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.replies: list[tuple[int, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import json

        assert request.url.path == f"/bot{TOKEN}/sendMessage"
        self.sent.append(json.loads(request.content))
        status, body = self.replies.pop(0) if self.replies else (200, {"ok": True, "result": {}})
        return httpx.Response(status, json=body)


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(recreate_database(TEST_DB))
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean(monkeypatch) -> AsyncIterator[None]:
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: NOW)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))  # noqa: S608 – own table names
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    app.state.settings.telegram_bot_token = ""
    for bid, code in ((PP1, "PP1"), (PP2, "PP2")):
        await event("branch.created", {"branch_id": str(bid), "code": code, "name_en": f"Branch {code}",
                                       "name_km": "", "is_active": True})  # fmt: skip
    yield
    app.state.settings.telegram_bot_token = ""
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
def telegram() -> FakeTelegram:
    fake = FakeTelegram()
    app.state.settings.telegram_bot_token = TOKEN
    app.state.telegram_transport = httpx.MockTransport(fake)
    yield fake
    app.state.telegram_transport = None


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def event(event_type: str, payload: dict, message_id: UUID | None = None) -> bool:
    return await process_message(db, ProcessedMessage, handle_event, message_id or uuid4(), event_type, payload)


async def messages() -> list[Message]:
    async with db.sessionmaker() as s:
        return list((await s.execute(select(Message).order_by(Message.created_at, Message.target))).scalars())


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,)) -> dict:
    return {"X-User-Id": str(uuid4()), "X-Role": role, "X-Branch-Ids": ",".join(map(str, branches)),
            "X-Is-Pharmacist": "false", "X-Permissions": permissions}  # fmt: skip


OWNER = user("owner", "*", ())
MANAGER = user("branch_manager", "notifications.manage")
