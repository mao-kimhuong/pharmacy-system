"""The dev clock (make seed-realistic): only with APP_ENV=development, never in production, only with the
service token; it reaches clock.now()/today(), database-dated columns and the internal calls it makes."""

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import APIRouter
from sqlalchemy import DateTime, String, create_engine, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from pharmacy_shared import clock
from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.config import BaseServiceSettings
from pharmacy_shared.db import Database, IdMixin, make_base
from pharmacy_shared.internal import InternalClient
from pharmacy_shared.testing import TEST_REDIS_URL

TOKEN = "t" * 40
PAST = "2026-08-15T10:30:00+07:00"


def make_app(environment: str = "local"):  # noqa: ANN201
    settings = BaseServiceSettings(_env_file=None, service_name="sales", api_prefix="/api/sales/v1",
                                   redis_url=TEST_REDIS_URL, service_token=TOKEN, environment=environment,
                                   outbox_relay_enabled=False, database_url="postgresql+asyncpg://x:y@localhost/z")  # fmt: skip
    router = APIRouter()
    seen: dict = {}

    @router.get("/time")
    async def what_time() -> dict:
        seen["header"] = InternalClient("http://x", "sales", TOKEN)._headers(None, None, None).get(clock.HEADER)
        return {"now": clock.now().isoformat(), "today": clock.today().isoformat(), "forwards": seen["header"]}

    return create_service_app(settings, Database(settings.database_url), router, "test")


async def ask(app, headers: dict) -> dict:  # noqa: ANN001
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return (await c.get("/api/sales/v1/time", headers=headers)).json()


def is_now(text: str) -> bool:
    return abs((datetime.fromisoformat(text) - datetime.now(UTC)).total_seconds()) < 60


async def test_development_with_the_service_token_moves_the_clock(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    got = await ask(make_app(), {clock.HEADER: PAST, "X-Service-Token": TOKEN})
    assert got["now"].startswith("2026-08-15T03:30") and got["today"] == "2026-08-15"
    assert got["forwards"].startswith("2026-08-15T03:30")  # internal calls run at the same time
    assert clock.override() is None  # nothing leaks out of the request


async def test_production_ignores_the_header_even_with_the_token(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")  # even if someone sets it there
    app = make_app("production")
    assert not any(m.cls is clock.DevClockMiddleware for m in app.user_middleware)
    got = await ask(app, {clock.HEADER: PAST, "X-Service-Token": TOKEN})
    assert is_now(got["now"]) and got["forwards"] is None


async def test_not_development_or_no_token_ignores_it(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    app = make_app()
    assert not any(m.cls is clock.DevClockMiddleware for m in app.user_middleware)
    assert is_now((await ask(app, {clock.HEADER: PAST, "X-Service-Token": TOKEN}))["now"])
    monkeypatch.setenv("APP_ENV", "development")
    dev = make_app()
    for headers in ({clock.HEADER: PAST}, {clock.HEADER: PAST, "X-Service-Token": "wrong"},
                    {clock.HEADER: "not a time", "X-Service-Token": TOKEN}):  # fmt: skip
        assert is_now((await ask(dev, headers))["now"]), headers


def test_database_dated_columns_take_the_dev_clock_and_only_then() -> None:
    Base = make_base()

    class Row(IdMixin, Base):
        __tablename__ = "rows"
        name: Mapped[str] = mapped_column(String(10))
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        token = clock.set_override(datetime.fromisoformat(PAST))
        try:
            s.add(Row(name="seeded"))
            s.flush()
        finally:
            clock.reset_override(token)
        s.add(Row(name="live"))
        s.commit()
        got = {r.name: r.created_at for r in s.execute(select(Row)).scalars()}
    assert got["seeded"].replace(tzinfo=UTC).date().isoformat() == "2026-08-15"
    assert got["live"].year == datetime.now(UTC).year and got["live"].date() != got["seeded"].date()


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError):
        clock.set_override(datetime(2026, 8, 15, 10, 30))
