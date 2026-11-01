"""Purchasing tests run against a real PostgreSQL + Redis (make test starts them)."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_purchasing"
os.environ["DATABASE_URL"] = test_database_url(TEST_DB)
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"
os.environ["EVENT_CONSUMER_ENABLED"] = "false"
SERVICE_TOKEN = "test-service-token-0123456789abcdef"
os.environ.update(SERVICE_TOKEN=SERVICE_TOKEN, EXPIRY_JOB_ENABLED="false", STORAGE_BUCKET_CHECK="false",
                  REORDER_JOB_ENABLED="false")  # fmt: skip

# Fill-by-transfer runs against the REAL inventory app (own test database), like the sale saga tests.
import inventory_service.config as inventory_config  # noqa: E402

inventory_config.get_settings().database_url = test_database_url("test_purchasing_inventory")

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402
from purchasing_service.db import db  # noqa: E402
from purchasing_service.main import app  # noqa: E402
from purchasing_service.models import ProcessedMessage  # noqa: E402
from purchasing_service.services.events import handle_event  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/purchasing/v1"
TODAY = date(2026, 10, 27)
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")
PP2 = UUID("00000000-0000-0000-0000-0000000000a2")


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(recreate_database(TEST_DB))
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    command.upgrade(cfg, "head")
    inventory_url = inventory_config.get_settings().database_url
    asyncio.run(recreate_database(inventory_url.rsplit("/", 1)[1]))
    inv = Config(str(SERVICE_DIR.parent / "inventory" / "alembic.ini"))
    inv.set_main_option("script_location", str(SERVICE_DIR.parent / "inventory" / "migrations"))
    command.upgrade(inv, "head")


@pytest.fixture(autouse=True)
async def clean(monkeypatch) -> AsyncIterator[None]:
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 27, 3, 0, tzinfo=UTC))  # 10:00 in Phnom Penh
    async with db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE payment_allocations, supplier_payments, receipt_lines, receipts, po_lines, purchase_orders,"
            " suppliers, supplier_groups, doc_sequences, product_pack_units, products, known_branches,"
            " processed_messages, outbox, purchase_request_lines, purchase_requests, po_groups,"
            " supplier_credit_allocations, supplier_credits, supplier_refunds, supplier_return_lines, supplier_returns"
            " CASCADE"
        ))  # fmt: skip
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    await event("branch.created", {"branch_id": str(PP1), "code": "PP1", "name_km": "សាខា១", "name_en": "Phnom Penh 1",
                                   "is_active": True})  # fmt: skip
    await event("branch.created", {"branch_id": str(PP2), "code": "PP2", "name_km": "សាខា២", "name_en": "Phnom Penh 2",
                                   "is_active": True})  # fmt: skip
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def event(event_type: str, payload: dict) -> None:
    await process_message(db, ProcessedMessage, handle_event, uuid4(), event_type, payload)


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,)) -> dict[str, str]:
    """Headers Traefik passes after /verify."""
    return {
        "X-User-Id": str(uuid4()),
        "X-Role": role,
        "X-Branch-Ids": ",".join(str(b) for b in branches),
        "X-Is-Pharmacist": "false",
        "X-Permissions": permissions,
    }


OWNER = user("owner", "*", ())
# Default grants (services/auth/auth_service/permissions.py)
MANAGER = user("branch_manager", "contacts.suppliers,purchasing.order,purchasing.receive,purchasing.over_receive,"
               "purchasing.pay,inventory.view")  # fmt: skip
CASHIER = user("cashier", "pos.sell,inventory.view,inventory.stock_in,purchasing.receive")
PHARMACIST = user("pharmacist", "pos.sell,purchasing.receive")
OTHER_MANAGER = user("branch_manager", "contacts.suppliers,purchasing.order,purchasing.receive,purchasing.pay",
                     (PP2,))  # fmt: skip


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def outbox() -> list[tuple[str, dict]]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT event_type, payload FROM outbox ORDER BY seq"))
        return [(r[0], r[1] if isinstance(r[1], dict) else json.loads(r[1])) for r in rows]


async def audits() -> list[dict]:
    return [p for t, p in await outbox() if t == "audit.recorded"]


async def add_product(sku: str, base: str = "tablet", packs: tuple[tuple[str, int], ...] = (("strip", 10), ("box", 100)),
                      controlled: str | None = None, active: bool = True) -> dict:  # fmt: skip
    """A medicine.created event as the catalog sends it; returns {pack name: id, "id": medicine id}."""
    medicine_id = uuid4()
    units = [(base, 1), *packs]
    pack_ids = {name: uuid4() for name, _ in units}
    await event("medicine.created", {
        "medicine_id": str(medicine_id), "version": 1, "sku": sku, "brand_name": sku.title(),
        "generic_name": f"{sku.lower()} generic", "strength": "500mg", "dosage_form": base,
        "name_km": "ថ្នាំ", "base_unit": base, "is_rx_only": bool(controlled), "controlled_schedule": controlled,
        "is_active": active,
        "pack_units": [{"id": str(pack_ids[name]), "name": name, "qty_in_base": qty, "barcode": None,
                        "sell_price": "1.00", "is_base": qty == 1, "is_active": True} for name, qty in units],
    })  # fmt: skip
    return {"id": str(medicine_id), **{name: str(pid) for name, pid in pack_ids.items()}}


async def create_supplier(client, code: str = "DKSH", **extra) -> dict:
    body = {"code": code, "name": f"{code} Cambodia", "payment_terms_days": 30, **extra}
    r = await client.post(f"{PREFIX}/suppliers", json=body, headers=OWNER)
    assert r.status_code == 201, r.text
    return r.json()


async def create_po(client, supplier: dict, lines: list[tuple[dict, str, int, str]], branch: UUID = PP1,
                    headers=None, send: bool = False) -> dict:  # fmt: skip
    """lines: (product, pack unit name, qty, unit cost)."""
    body = {
        "branch_id": str(branch), "supplier_id": supplier["id"],
        "lines": [{"medicine_id": p["id"], "pack_unit_id": p[pack], "qty": qty, "unit_cost": cost}
                  for p, pack, qty, cost in lines],
    }  # fmt: skip
    r = await client.post(f"{PREFIX}/purchase-orders", json=body, headers=headers or OWNER)
    assert r.status_code == 201, r.text
    po = r.json()
    if send:
        r = await client.post(f"{PREFIX}/purchase-orders/{po['id']}/send", headers=headers or OWNER)
        assert r.status_code == 200, r.text
        po = r.json()
    return po


async def receive(client, po: dict, lines: list[dict], headers=None, key: dict | None = None, **extra):
    return await client.post(
        f"{PREFIX}/purchase-orders/{po['id']}/receive", json={"lines": lines, **extra},
        headers={**(headers or OWNER), **(key or idem())},
    )  # fmt: skip
