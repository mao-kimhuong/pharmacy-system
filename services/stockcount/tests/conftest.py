"""Stock-take tests: real Postgres + Redis; the REAL inventory app runs in-process
with its own database (snapshot, movements since, count.approved), fake auth for PINs."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

SERVICE_TOKEN = "test-service-token-0123456789abcdef"
os.environ.update(
    DATABASE_URL=test_database_url("test_stockcount"), REDIS_URL=TEST_REDIS_URL, OUTBOX_RELAY_ENABLED="false",
    EVENT_CONSUMER_ENABLED="false", EXPIRY_JOB_ENABLED="false", STORAGE_BUCKET_CHECK="false",
    SERVICE_TOKEN=SERVICE_TOKEN,
)  # fmt: skip

import inventory_service.config as inventory_config  # noqa: E402

inventory_config.get_settings().database_url = test_database_url("test_stockcount_inventory")

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

import inventory_service.main as inventory_main  # noqa: E402
from inventory_service.db import db as inventory_db  # noqa: E402
from inventory_service.models import Batch, Stock  # noqa: E402
from inventory_service.models import ProcessedMessage as InventoryProcessed  # noqa: E402
from inventory_service.services.events import handle_event as inventory_handle  # noqa: E402
from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402
from pharmacy_shared.internal import InternalClient  # noqa: E402
from stockcount_service.db import db  # noqa: E402
from stockcount_service.main import app  # noqa: E402
from stockcount_service.models import OutboxEvent, ProcessedMessage  # noqa: E402
from stockcount_service.services.clients import Clients, get_clients  # noqa: E402
from stockcount_service.services.events import handle_event  # noqa: E402

from .fake_auth import FakeAuth  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "/api/stockcount/v1"
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")
PP2 = UUID("00000000-0000-0000-0000-0000000000a2")
SUPPLIER = UUID("00000000-0000-0000-0000-00000000005a")
AUTH = FakeAuth()


def _migrate(service: str, url: str) -> None:
    asyncio.run(recreate_database(url.rsplit("/", 1)[1]))
    cfg = Config(str(ROOT / service / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / service / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def databases() -> None:
    _migrate("stockcount", test_database_url("test_stockcount"))
    _migrate("inventory", inventory_config.get_settings().database_url)


@pytest.fixture(autouse=True)
async def clean(monkeypatch) -> AsyncIterator[None]:
    monkeypatch.setattr(clock, "today", lambda: date(2026, 10, 27))
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 27, 3, 0, tzinfo=UTC))
    async with db.engine.begin() as conn:
        await conn.execute(text("TRUNCATE count_entries, count_lines, counts, doc_sequences, known_branches,"
                                " branch_settings, processed_messages, outbox CASCADE"))  # fmt: skip
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
    app.dependency_overrides[get_clients] = lambda: Clients(auth=AUTH, inventory=InternalClient(  # type: ignore[arg-type]
        "http://inventory", "stockcount", SERVICE_TOKEN, transport=httpx.ASGITransport(app=inventory_main.app)))
    yield
    app.dependency_overrides.clear()
    for d in (db, inventory_db):
        await d.dispose()
    for a in (app, inventory_main.app):
        await a.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def event(event_type: str, payload: dict) -> None:
    await process_message(db, ProcessedMessage, handle_event, uuid4(), event_type, payload)


async def inventory_event(event_type: str, payload: dict, message_id: UUID | None = None) -> None:
    await process_message(inventory_db, InventoryProcessed, inventory_handle, message_id or uuid4(), event_type, payload)


async def everywhere(event_type: str, payload: dict) -> None:
    await event(event_type, payload)
    await inventory_event(event_type, payload)


async def relay_approved() -> None:
    """count.approved from the stockcount outbox → inventory (outbox id = message id)."""
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.event_type == "count.approved")
                                .order_by(OutboxEvent.seq))).scalars().all()  # fmt: skip
    for row in rows:
        await inventory_event(row.event_type, row.payload, row.id)


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,)) -> dict[str, str]:
    return {"X-User-Id": str(uuid4()), "X-Role": role, "X-Branch-Ids": ",".join(map(str, branches)),
            "X-Is-Pharmacist": "true", "X-Permissions": permissions}  # fmt: skip


OWNER = user("owner", "*", ())
COUNTER_A = user("cashier", "stockcount.count")
COUNTER_B = user("cashier", "stockcount.count")
APPROVER = user("pharmacist", "stockcount.count,stockcount.approve")


async def add_product(sku: str, controlled: str | None = None, barcode: str | None = None) -> str:
    medicine_id = str(uuid4())
    await inventory_event("medicine.created", {
        "medicine_id": medicine_id, "version": 1, "sku": sku, "brand_name": sku.title(), "generic_name": "G",
        "strength": "", "dosage_form": "tablet", "name_km": "", "base_unit": "tablet", "is_rx_only": bool(controlled),
        "controlled_schedule": controlled, "is_active": True,
        "pack_units": [{"id": str(uuid4()), "name": "tablet", "qty_in_base": 1, "barcode": barcode,
                        "sell_price": "0.10", "is_base": True, "is_active": True}],
    })  # fmt: skip
    return medicine_id


async def receive(medicine_id: str, qty: int, cost: str = "0.0500", lot: str = "L1") -> None:
    await inventory_event("goods.received", {
        "receipt_id": str(uuid4()), "number": "PP1-GRN-2026-000001", "po_id": str(uuid4()),
        "po_number": "PP1-PO-2026-000001", "branch_id": str(PP1), "supplier_id": str(SUPPLIER),
        "received_at": "2026-10-20T03:00:00+00:00", "received_by": None,
        "lines": [{"receipt_line_id": str(uuid4()), "medicine_id": medicine_id, "pack_unit_id": str(uuid4()),
                   "qty_base": qty, "lot_no": lot, "expiry_date": "2028-01-31", "cost_per_base": cost,
                   "controlled_schedule": None, "is_controlled": False}]})  # fmt: skip


async def on_hand(medicine_id: str) -> int:
    async with inventory_db.sessionmaker() as s:
        return sum((await s.execute(select(Stock.qty_on_hand).join(Batch, Batch.id == Stock.batch_id)
                                    .where(Batch.medicine_id == UUID(medicine_id)))).scalars())  # fmt: skip


async def sell_now(medicine_id: str, qty: int) -> None:
    """A sale going on during the count (an "out" movement in inventory)."""
    from inventory_service.services.movements import apply_movement

    async with inventory_db.sessionmaker() as s:
        batch = (await s.execute(select(Batch).where(Batch.medicine_id == UUID(medicine_id)))).scalars().first()
        await apply_movement(s, branch_id=PP1, batch=batch, type="out", qty_base=-qty, ref_type="test",
                             ref_id=str(uuid4()))  # fmt: skip
        await s.commit()
