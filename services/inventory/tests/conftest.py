"""Inventory tests run against a real PostgreSQL + Redis (make test starts them)."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.redis import connect as connect_redis
from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_inventory"
os.environ["DATABASE_URL"] = test_database_url(TEST_DB)
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"
os.environ["EVENT_CONSUMER_ENABLED"] = "false"
os.environ["EXPIRY_JOB_ENABLED"] = "false"
os.environ["REORDER_JOB_ENABLED"] = "false"
SERVICE_TOKEN = "test-service-token-0123456789abcdef"
os.environ["SERVICE_TOKEN"] = SERVICE_TOKEN
S3_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT", "")
os.environ.update(STORAGE_BUCKET_CHECK="false", S3_ENDPOINT=S3_ENDPOINT or "http://127.0.0.1:9",
                  S3_BUCKET="test-inventory-files", S3_ACCESS_KEY="testkey123",
                  S3_SECRET_KEY="test-secret-0123456789abcdef")  # fmt: skip

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from inventory_service.db import db  # noqa: E402
from inventory_service.main import app  # noqa: E402
from inventory_service.models import ProcessedMessage  # noqa: E402
from inventory_service.services.events import handle_event  # noqa: E402
from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/inventory/v1"
TODAY = date(2026, 10, 27)
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")
PP2 = UUID("00000000-0000-0000-0000-0000000000a2")
SUPPLIER = UUID("00000000-0000-0000-0000-00000000005a")


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
            "TRUNCATE reservation_lines, reservations, quarantine_entries, movements, stock, batches, stock_ins, opening_lines, opening_balances, initialize_locks,"
            " product_pack_units, products, known_branches, known_suppliers, processed_messages, outbox, shrinkages,"
            " shelf_locations, branch_settings, doc_sequences, transfer_discrepancies, transfer_picks, transfer_lines,"
            " transfers, transfer_request_lines, transfer_requests, reorder_lines, reorder_lists, reorder_settings,"
            " open_po_lines, alerts_sent, recall_lines, recalls CASCADE"
        ))  # fmt: skip
    redis = connect_redis(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    for bid, code in ((PP1, "PP1"), (PP2, "PP2")):
        await event("branch.created", {"branch_id": str(bid), "code": code, "name_km": "សាខា",
                                       "name_en": f"Branch {code}", "is_active": True})  # fmt: skip
    await event("supplier.created", {"supplier_id": str(SUPPLIER), "code": "DKSH", "name": "DKSH Cambodia",
                                     "name_km": "", "phone": "", "address": "", "payment_terms_days": 30,
                                     "is_active": True})  # fmt: skip
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def event(event_type: str, payload: dict) -> bool:
    return await process_message(db, ProcessedMessage, handle_event, uuid4(), event_type, payload)


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,)) -> dict[str, str]:
    return {
        "X-User-Id": str(uuid4()),
        "X-Role": role,
        "X-Branch-Ids": ",".join(str(b) for b in branches),
        "X-Is-Pharmacist": "false",
        "X-Permissions": permissions,
    }


OWNER = user("owner", "*", ())
MANAGER = user("branch_manager", "inventory.view,inventory.stock_in,inventory.adjust,inventory.initialize")
CASHIER = user("cashier", "pos.sell,products.view,inventory.view,inventory.stock_in,purchasing.receive")


INTERNAL = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "sales", "X-Acting-User-Id": str(uuid4()),
            "X-Acting-Role": "cashier"}  # fmt: skip
PHARMACIST = {**user("pharmacist", "inventory.view,inventory.adjust"), "X-Is-Pharmacist": "true"}


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def outbox() -> list[tuple[str, dict]]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT event_type, payload FROM outbox ORDER BY seq"))
        return [(r[0], r[1] if isinstance(r[1], dict) else json.loads(r[1])) for r in rows]


async def audits() -> list[dict]:
    return [p for t, p in await outbox() if t == "audit.recorded"]


async def scalar(sql: str):
    async with db.engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one()


async def add_product(sku: str = "PARA500", base: str = "tablet", packs=(("strip", 10), ("box", 100)),
                      controlled: str | None = None, category: str | None = None) -> dict:  # fmt: skip
    medicine_id = uuid4()
    units = [(base, 1), *packs]
    ids = {name: uuid4() for name, _ in units}
    await event("medicine.created", {
        "medicine_id": str(medicine_id), "version": 1, "sku": sku, "brand_name": sku.title(),
        "generic_name": "Generic", "strength": "500mg", "dosage_form": base, "name_km": "ថ្នាំ",
        "base_unit": base, "is_rx_only": bool(controlled), "controlled_schedule": controlled, "is_active": True,
        "category": {"id": category, "name_en": "Cat", "name_km": ""} if category else None,
        "pack_units": [{"id": str(ids[n]), "name": n, "qty_in_base": q, "barcode": None, "sell_price": "1.00",
                        "is_base": q == 1, "is_active": True} for n, q in units],
    })  # fmt: skip
    return {"id": str(medicine_id), **{n: str(i) for n, i in ids.items()}}


def goods_received(product: dict, lots: list[tuple[str, str, int, str]], branch: UUID = PP1) -> dict:
    """lots: (lot, expiry, qty_base, cost_per_base)."""
    return {
        "receipt_id": str(uuid4()), "number": "PP1-GRN-2026-000001", "po_id": str(uuid4()),
        "po_number": "PP1-PO-2026-000001", "branch_id": str(branch), "supplier_id": str(SUPPLIER),
        "received_at": "2026-10-27T03:00:00+00:00", "received_by": str(uuid4()),
        "lines": [{"receipt_line_id": str(uuid4()), "medicine_id": product["id"], "pack_unit_id": product["box"],
                   "qty_base": qty, "lot_no": lot, "expiry_date": expiry, "cost_per_base": cost,
                   "controlled_schedule": None, "is_controlled": False} for lot, expiry, qty, cost in lots],
    }  # fmt: skip


async def stock_of(client, headers=OWNER, **params) -> list[dict]:
    r = await client.get(f"{PREFIX}/stock", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]
