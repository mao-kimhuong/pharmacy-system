"""Reports tests: a real Postgres test database built with the service's own
migrations; events go through the real handlers (services/events.py)."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_reports"
SERVICE_TOKEN = "test-service-token-0123456789abcdef"
os.environ.update(DATABASE_URL=test_database_url(TEST_DB), REDIS_URL=TEST_REDIS_URL, OUTBOX_RELAY_ENABLED="false",
                  EVENT_CONSUMER_ENABLED="false", SERVICE_TOKEN=SERVICE_TOKEN)  # fmt: skip

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402
from reports_service.db import db  # noqa: E402
from reports_service.main import app  # noqa: E402
from reports_service.models import Base, ProcessedMessage  # noqa: E402
from reports_service.services.events import handle_event  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/reports/v1"
TODAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 27, 5, 0, tzinfo=UTC)  # 12:00 in Phnom Penh
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")
PP2 = UUID("00000000-0000-0000-0000-0000000000a2")
INTERNAL = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "notification"}


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
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables if t.name != "alembic_version")
    async with db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))  # noqa: S608 – own table names
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    for bid, code in ((PP1, "PP1"), (PP2, "PP2")):
        await event("branch.created", {"branch_id": str(bid), "code": code, "name_en": f"Branch {code}",
                                       "name_km": "សាខា", "is_active": True})  # fmt: skip
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def event(event_type: str, payload: dict, message_id: UUID | None = None) -> bool:
    return await process_message(db, ProcessedMessage, handle_event, message_id or uuid4(), event_type, payload)


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,), user_id: UUID | None = None) -> dict:
    return {"X-User-Id": str(user_id or uuid4()), "X-Role": role, "X-Branch-Ids": ",".join(map(str, branches)),
            "X-Is-Pharmacist": "false", "X-Permissions": permissions}  # fmt: skip


OWNER = user("owner", "*", ())
MANAGER = user("branch_manager", "dashboard.view,reports.sales,reports.stock,reports.purchases,purchasing.pay")


async def product(sku: str = "PARA500", category: UUID | None = None) -> UUID:
    mid = uuid4()
    await event("medicine.created", {
        "medicine_id": str(mid), "version": 1, "sku": sku, "brand_name": sku.title(), "generic_name": "Generic",
        "base_unit": "tablet", "is_rx_only": False, "controlled_schedule": None, "is_active": True,
        "category_id": str(category) if category else None,
        "pack_units": [{"id": str(uuid4()), "name": "tablet", "qty_in_base": 1, "barcode": None, "sell_price": "0.10",
                        "is_base": True, "is_active": True}]})  # fmt: skip
    return mid


def line(medicine: UUID, qty_base: int, net: str, cost: str, **extra) -> dict:
    return {"line_no": extra.pop("line_no", 1), "line_id": str(extra.pop("line_id", uuid4())),
            "medicine_id": str(medicine), "pack_unit_id": str(uuid4()), "sku": extra.pop("sku", "PARA500"),
            "name": "Para", "pack_unit": "tablet", "qty": qty_base, "qty_in_base": 1, "qty_base": qty_base,
            "unit_price": "0.10", "line_total": extra.pop("line_total", net), "cost": cost, "returned_qty_base": 0,
            "rx": None, "rx_item_id": None, "promotion_ids": [], "promo_discount": extra.pop("promo", "0.00"),
            "manual_discount": "0.00", "net": net, "is_hamper": False, "staff_id": extra.pop("staff", None),
            "batches": [], **extra}  # fmt: skip


def invoice(number: str, lines: list[dict], *, at: str = "2026-10-27T03:00:00+00:00", version: int = 1,
            status: str = "completed", rate: int = 4100, payments: list[dict] | None = None, branch: UUID = PP1,
            cashier: UUID | None = None, returns: list[dict] | None = None, cancelled_at: str | None = None,
            invoice_id: UUID | None = None, change: str = "0.00", customer: UUID | None = None) -> dict:  # fmt: skip
    total = sum(float(x["net"]) for x in lines)
    return {"invoice_id": str(invoice_id or uuid4()), "version": version, "number": number, "status": status,
            "branch": {"id": str(branch), "code": "PP1"}, "cashier_id": str(cashier or uuid4()), "completed_at": at,
            "customer": {"id": str(customer), "name": "C"} if customer else None, "lines": lines,
            "subtotal": f"{total:.2f}", "discount": "0.00", "total": f"{total:.2f}", "khr_per_usd": rate,
            "total_khr": round(total * rate / 100) * 100, "payments": payments if payments is not None else
            [{"method": "cash", "currency": "USD", "amount": f"{total:.2f}", "amount_usd": f"{total:.2f}"}],
            "credit_amount": "0.00", "change_usd": change, "returned_total": "0.00", "cancelled_at": cancelled_at,
            "cancel_reason": "x" if cancelled_at else None, "returns": returns or []}  # fmt: skip


async def get(client, path: str, who: dict = OWNER, **params):  # noqa: ANN001, ANN003, ANN201
    return await client.get(f"{PREFIX}/{path}", params={k: str(v) for k, v in params.items()}, headers=who)
