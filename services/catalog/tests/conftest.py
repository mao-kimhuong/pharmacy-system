"""Catalog tests run against a real PostgreSQL + Redis (make test starts them)."""

import asyncio
import io
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_catalog"
os.environ["DATABASE_URL"] = test_database_url(TEST_DB)
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

from catalog_service.db import db  # noqa: E402
from catalog_service.main import app  # noqa: E402
from catalog_service.services.spreadsheet import KEYS  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO = SERVICE_DIR.parents[1]
SAMPLES = REPO / "docs" / "samples"
PREFIX = "/api/catalog/v1"


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(recreate_database(TEST_DB))
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean() -> AsyncIterator[None]:
    async with db.engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE import_rows, imports, pack_units, medicines, categories, brands, outbox CASCADE")
        )
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def user(role: str = "owner", permissions: str = "*", branches: tuple[UUID, ...] = ()) -> dict[str, str]:
    """Headers Traefik passes after /verify."""
    return {
        "X-User-Id": str(uuid4()),
        "X-Role": role,
        "X-Branch-Ids": ",".join(str(b) for b in branches),
        "X-Is-Pharmacist": "false",
        "X-Permissions": permissions,
    }


OWNER = user()
# Default grants from services/auth/auth_service/permissions.py
CASHIER = user("cashier", "dashboard.view,pos.sell,sales.view,products.view,inventory.view")
PHARMACIST = user("pharmacist", "pos.sell,products.view,labels.print")
MANAGER = user("branch_manager", "products.view,products.manage,products.import,labels.print")


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def outbox() -> list[tuple[str, dict]]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT event_type, payload FROM outbox ORDER BY seq"))
        return [(r[0], r[1] if isinstance(r[1], dict) else json.loads(r[1])) for r in rows]


async def audits() -> list[dict]:
    return [p for t, p in await outbox() if t == "audit.recorded"]


async def count(table: str) -> int:
    # Table names are constants of the tests.
    async with db.engine.connect() as conn:
        return (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608


def medicine_body(sku: str = "PARA500", **extra) -> dict:
    return {
        "sku": sku,
        "brand_name": "Panadol",
        "generic_name": "Paracetamol",
        "strength": "500mg",
        "dosage_form": "tablet",
        "name_km": "ប៉ារ៉ាសេតាម៉ុល",
        "base_unit": "tablet",
        "base_price": "0.10",
        "pack_units": [
            {"name": "strip", "qty_in_base": 10, "barcode": f"{sku}-S", "sell_price": "0.90"},
            {"name": "box", "qty_in_base": 100, "barcode": f"{sku}-B", "sell_price": "8.50"},
        ],
        **extra,
    }


async def create_medicine(client, sku: str = "PARA500", headers=None, **extra) -> dict:
    r = await client.post(f"{PREFIX}/medicines", json=medicine_body(sku, **extra), headers=headers or OWNER)
    assert r.status_code == 201, r.text
    return r.json()


def xlsx(rows: list[dict], header: list[str] | None = None, sheet: str = "Products") -> bytes:
    """A workbook with the import columns; rows give only the cells they need."""
    header = header or list(KEYS)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for row in rows:
        ws.append([row.get(k, "") for k in header])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def product_rows(sku: str = "AMOX500", barcode_prefix: str = "885000", **product) -> list[dict]:
    """Capsule / strip / box rows of one product, product columns on the first row only."""
    first = {
        "sku": sku,
        "brand_name": "Amoxil",
        "generic_name": "Amoxicillin",
        "strength": "500mg",
        "dosage_form": "capsule",
        "name_km": "អាម៉ុកស៊ីស៊ីលីន",
        "base_unit": "capsule",
        "rx_only": "yes",
        **product,
    }
    return [
        {**first, "pack_unit": first["base_unit"], "qty_in_base": 1, "barcode": f"{barcode_prefix}1",
         "sell_price_usd": "0.25"},
        {"sku": sku, "pack_unit": "strip", "qty_in_base": 10, "barcode": f"{barcode_prefix}2",
         "sell_price_usd": "2.30"},
        {"sku": sku, "pack_unit": "box", "qty_in_base": 100, "barcode": f"{barcode_prefix}3",
         "sell_price_usd": "21.00"},
    ]  # fmt: skip


async def upload(client, content: bytes, name: str = "products.xlsx", headers=None) -> httpx.Response:
    files = {"file": (name, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    return await client.post(f"{PREFIX}/imports", files=files, headers=headers or OWNER)


async def commit(client, import_id: str, headers=None, **body) -> httpx.Response:
    return await client.post(
        f"{PREFIX}/imports/{import_id}/commit", json=body, headers={**(headers or OWNER), **idem()}
    )
