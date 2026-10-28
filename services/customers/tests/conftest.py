"""Customers tests run against a real PostgreSQL + Redis (make test starts them)."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_customers"
SERVICE_TOKEN = "test-service-token-0123456789abcdef"
os.environ["DATABASE_URL"] = test_database_url(TEST_DB)
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"
os.environ["EVENT_CONSUMER_ENABLED"] = "false"
os.environ["SERVICE_TOKEN"] = SERVICE_TOKEN

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

from customers_service.db import db  # noqa: E402
from customers_service.main import app  # noqa: E402
from customers_service.models import ProcessedMessage  # noqa: E402
from customers_service.services.events import handle_event  # noqa: E402
from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/customers/v1"
TODAY = date(2026, 10, 27)
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(recreate_database(TEST_DB))
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean(monkeypatch) -> AsyncIterator[None]:
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 27, 3, 0, tzinfo=UTC))  # 10:00 in Phnom Penh
    async with db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE customer_allocations, customer_payments, customer_debts, ledger_entries, customers,"
            " customer_groups, doc_sequences, known_branches, processed_messages, outbox CASCADE"))  # fmt: skip
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    await process_message(db, ProcessedMessage, handle_event, uuid4(), "branch.created", {
        "branch_id": str(PP1), "code": "PP1", "name_km": "", "name_en": "PP1", "is_active": True})  # fmt: skip
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,)) -> dict[str, str]:
    return {"X-User-Id": str(uuid4()), "X-Role": role, "X-Branch-Ids": ",".join(map(str, branches)),
            "X-Is-Pharmacist": "false", "X-Permissions": permissions}  # fmt: skip


OWNER = user("owner", "*", ())
MANAGER = user("branch_manager", "contacts.customers,customers.credit_limit")
CASHIER = user("cashier", "pos.sell,contacts.customers")
INTERNAL = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "sales", "X-Acting-User-Id": str(uuid4()),
            "X-Acting-Role": "cashier"}  # fmt: skip


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def outbox() -> list[tuple[str, dict]]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT event_type, payload FROM outbox ORDER BY seq"))
        return [(r[0], r[1] if isinstance(r[1], dict) else json.loads(r[1])) for r in rows]


async def audits() -> list[dict]:
    return [p for t, p in await outbox() if t == "audit.recorded"]


async def create_customer(client, phone: str = "012 345 678", limit: str = "100.00", **extra) -> dict:
    r = await client.post(f"{PREFIX}/customers", json={"phone": phone, "name": "Sok Dara", "credit_limit": limit,
                                                       **extra}, headers=OWNER)  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def charge(
    client, customer: dict, amount: str, invoice_id=None, invoice_no: str = "PP1-INV-2026-000001"
):
    return await client.post("/internal/v1/credit/charge", headers=INTERNAL, json={
        "invoice_id": str(invoice_id or uuid4()), "invoice_no": invoice_no, "customer_id": customer["id"],
        "branch_id": str(PP1), "amount": amount})  # fmt: skip


async def reverse(client, customer: dict, invoice_id, kind: str = "cancel", **extra):
    return await client.post("/internal/v1/credit/reverse", headers=INTERNAL, json={
        "invoice_id": str(invoice_id), "customer_id": customer["id"], "branch_id": str(PP1), "kind": kind,
        **extra})  # fmt: skip


async def get(client, customer: dict) -> dict:
    return (await client.get(f"{PREFIX}/customers/{customer['id']}", headers=OWNER)).json()
