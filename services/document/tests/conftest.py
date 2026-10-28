"""Document tests run against a real PostgreSQL + Redis (make test starts them).
Label PDFs need Pango (in the Docker image / make test-docker; on a Mac:
brew install pango); without it those tests are skipped, with that reason."""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_document"
os.environ["DATABASE_URL"] = test_database_url(TEST_DB)
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"
os.environ["EVENT_CONSUMER_ENABLED"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

from document_service.db import db  # noqa: E402
from document_service.main import app  # noqa: E402
from document_service.services.events import upsert_product  # noqa: E402

try:
    import weasyprint  # noqa: F401

    PDF_REASON = ""
except (ImportError, OSError) as exc:  # Pango missing
    PDF_REASON = (
        f"WeasyPrint cannot load Pango ({exc.__class__.__name__}); brew install pango, or make test-docker"
    )
needs_pdf = pytest.mark.skipif(bool(PDF_REASON), reason=PDF_REASON or "ok")

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/documents/v1"


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
            text(
                "TRUNCATE product_pack_units, products, purchase_orders, invoices, processed_messages, outbox CASCADE"
            )
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
    return {
        "X-User-Id": str(uuid4()),
        "X-Role": role,
        "X-Branch-Ids": ",".join(str(b) for b in branches),
        "X-Is-Pharmacist": "false",
        "X-Permissions": permissions,
    }


OWNER = user()
PHARMACIST = user("pharmacist", "pos.sell,products.view,labels.print")
CASHIER = user("cashier", "pos.sell,sales.view,products.view")


def medicine_event(version: int = 1, **extra) -> dict:
    """A medicine.* payload as the catalog service sends it."""
    medicine_id = extra.pop("medicine_id", str(uuid4()))
    return {
        "medicine_id": medicine_id,
        "version": version,
        "sku": "PARA500",
        "brand_name": "Panadol",
        "generic_name": "Paracetamol",
        "strength": "500mg",
        "dosage_form": "tablet",
        "name_km": "ប៉ាណាដុល ប៉ារ៉ាសេតាម៉ុល",
        "category": None,
        "brand": None,
        "manufacturer": "GSK",
        "base_unit": "tablet",
        "is_rx_only": False,
        "controlled_schedule": None,
        "storage": "room",
        "reorder_level": 0,
        "is_active": True,
        "pack_units": [
            {"id": str(uuid4()), "name": "tablet", "qty_in_base": 1, "barcode": "8841000100017",
             "sell_price": "0.05", "is_base": True, "is_active": True},
            {"id": str(uuid4()), "name": "box", "qty_in_base": 120, "barcode": "8841000100031",
             "sell_price": "5.00", "is_base": False, "is_active": True},
        ],
        **extra,
    }  # fmt: skip


async def seed(**extra) -> dict:
    payload = medicine_event(**extra)
    async with db.sessionmaker() as session, session.begin():
        await upsert_product(session, payload)
    return payload


def pack_id(payload: dict, name: str = "box") -> str:
    return next(p["id"] for p in payload["pack_units"] if p["name"] == name)
