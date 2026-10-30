"""Controlled-register tests: real Postgres + Redis; the REAL inventory app runs
in-process with its own database (its stock.changed events are relayed here),
and a fake auth hands out PIN tokens."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

SERVICE_TOKEN = "test-service-token-0123456789abcdef"
os.environ.update(
    DATABASE_URL=test_database_url("test_controlled"), REDIS_URL=TEST_REDIS_URL, OUTBOX_RELAY_ENABLED="false",
    EVENT_CONSUMER_ENABLED="false", CHECK_JOB_ENABLED="false", EXPIRY_JOB_ENABLED="false",
    STORAGE_BUCKET_CHECK="false", SERVICE_TOKEN=SERVICE_TOKEN,
)  # fmt: skip

import inventory_service.config as inventory_config  # noqa: E402

inventory_config.get_settings().database_url = test_database_url("test_controlled_inventory")

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

import inventory_service.main as inventory_main  # noqa: E402
from controlled_service.db import db  # noqa: E402
from controlled_service.main import app  # noqa: E402
from controlled_service.models import ProcessedMessage  # noqa: E402
from controlled_service.services.clients import Clients, get_clients  # noqa: E402
from controlled_service.services.events import handle_event  # noqa: E402
from inventory_service.db import db as inventory_db  # noqa: E402
from inventory_service.models import OutboxEvent as InventoryOutbox  # noqa: E402
from inventory_service.models import ProcessedMessage as InventoryProcessed  # noqa: E402
from inventory_service.services.events import handle_event as inventory_handle  # noqa: E402
from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402
from pharmacy_shared.internal import InternalClient  # noqa: E402

from .fake_auth import FakeAuth  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "/api/controlled/v1"
TODAY = date(2026, 10, 27)
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")
PP2 = UUID("00000000-0000-0000-0000-0000000000a2")
SUPPLIER = UUID("00000000-0000-0000-0000-00000000005a")


def _migrate(service: str, url: str) -> None:
    asyncio.run(recreate_database(url.rsplit("/", 1)[1]))
    cfg = Config(str(ROOT / service / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / service / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def databases() -> None:
    _migrate("controlled", test_database_url("test_controlled"))
    _migrate("inventory", inventory_config.get_settings().database_url)


AUTH = FakeAuth()


@pytest.fixture(autouse=True)
async def clean(monkeypatch) -> AsyncIterator[None]:
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 27, 3, 0, tzinfo=UTC))
    async with db.engine.begin() as conn:
        # the append-only trigger would refuse TRUNCATE: tests clean up as replication (superuser only)
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await conn.execute(text(
            "TRUNCATE register_entries, discrepancies, adjust_requests, products, known_staff, known_branches,"
            " watermark, processed_messages, outbox"))  # fmt: skip
    async with inventory_db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE reservation_lines, reservations, quarantine_entries, movements, stock, batches, stock_ins,"
            " product_pack_units, products, known_branches, known_suppliers, processed_messages, outbox, shrinkages,"
            " shelf_locations, branch_settings, doc_sequences CASCADE"))  # fmt: skip
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    AUTH.tokens.clear()
    for bid, code in ((PP1, "PP1"), (PP2, "PP2")):
        await everywhere("branch.created", {"branch_id": str(bid), "code": code, "name_km": "សាខា",
                                            "name_en": f"Branch {code}", "is_active": True})  # fmt: skip
    app.dependency_overrides[get_clients] = lambda: clients()
    yield
    app.dependency_overrides.clear()
    for d in (db, inventory_db):
        await d.dispose()
    for a in (app, inventory_main.app):
        await a.state.redis.close()


def clients() -> Clients:
    inventory = InternalClient("http://inventory", "controlled", SERVICE_TOKEN,
                               transport=httpx.ASGITransport(app=inventory_main.app))  # fmt: skip
    return Clients(auth=AUTH, inventory=inventory)  # type: ignore[arg-type]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def event(event_type: str, payload: dict, message_id: UUID | None = None) -> None:
    await process_message(db, ProcessedMessage, handle_event, message_id or uuid4(), event_type, payload)


async def everywhere(event_type: str, payload: dict) -> None:
    await event(event_type, payload)
    await process_message(inventory_db, InventoryProcessed, inventory_handle, uuid4(), event_type, payload)


async def relay() -> int:
    """stock.changed from inventory's outbox → the register (outbox id = message id,
    so a second relay delivers nothing new)."""
    async with inventory_db.sessionmaker() as s:
        rows = (await s.execute(select(InventoryOutbox).where(InventoryOutbox.event_type == "stock.changed")
                                .order_by(InventoryOutbox.seq))).scalars().all()  # fmt: skip
    for row in rows:
        await event(row.event_type, row.payload, row.id)
    return len(rows)


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,)) -> dict[str, str]:
    return {"X-User-Id": str(uuid4()), "X-Role": role, "X-Branch-Ids": ",".join(map(str, branches)),
            "X-Is-Pharmacist": "true", "X-Permissions": permissions}  # fmt: skip


PHARMACIST = user("pharmacist", "controlled.view,controlled.adjust,controlled.witness")
MANAGER = user("branch_manager", "controlled.view,controlled.adjust,controlled.resolve,controlled.witness")
CASHIER = user("cashier", "pos.sell")


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def add_controlled(sku: str = "DIAZ5") -> str:
    medicine_id = str(uuid4())
    await everywhere("medicine.created", {
        "medicine_id": medicine_id, "version": 1, "sku": sku, "brand_name": "Valium", "generic_name": "Diazepam",
        "strength": "5mg", "dosage_form": "tablet", "name_km": "ឌីអាហ្សេប៉ាម", "base_unit": "tablet",
        "is_rx_only": True, "controlled_schedule": "IV", "is_active": True,
        "pack_units": [{"id": str(uuid4()), "name": "tablet", "qty_in_base": 1, "barcode": None,
                        "sell_price": "0.10", "is_base": True, "is_active": True}],
    })  # fmt: skip
    return medicine_id


async def receive(medicine_id: str, qty: int = 100, lot: str = "D1", branch: UUID = PP1) -> None:
    await process_message(inventory_db, InventoryProcessed, inventory_handle, uuid4(), "goods.received", {
        "receipt_id": str(uuid4()), "number": "PP1-GRN-2026-000001", "po_id": str(uuid4()),
        "po_number": "PP1-PO-2026-000001", "branch_id": str(branch), "supplier_id": str(SUPPLIER),
        "received_at": "2026-10-20T03:00:00+00:00", "received_by": None,
        "lines": [{"receipt_line_id": str(uuid4()), "medicine_id": medicine_id, "pack_unit_id": str(uuid4()),
                   "qty_base": qty, "lot_no": lot, "expiry_date": "2028-01-31", "cost_per_base": "0.0500",
                   "controlled_schedule": "IV", "is_controlled": True}]})  # fmt: skip


async def batch_id(medicine_id: str, branch: UUID = PP1) -> str:
    from inventory_service.models import Batch

    async with inventory_db.sessionmaker() as s:
        return str((await s.execute(select(Batch.id).where(Batch.medicine_id == UUID(medicine_id)))).scalars().first())
