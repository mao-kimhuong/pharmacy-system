"""Prescription tests: real Postgres + Redis, and the test SeaweedFS for
attachments (skipped when TEST_S3_ENDPOINT is not set)."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.redis import connect as connect_redis
from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

SERVICE_TOKEN = "test-service-token-0123456789abcdef"
S3_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT", "")
os.environ.update(
    DATABASE_URL=test_database_url("test_prescription"), REDIS_URL=TEST_REDIS_URL, OUTBOX_RELAY_ENABLED="false",
    EVENT_CONSUMER_ENABLED="false", EXPIRY_JOB_ENABLED="false", STORAGE_BUCKET_CHECK="false",
    SERVICE_TOKEN=SERVICE_TOKEN, S3_ENDPOINT=S3_ENDPOINT or "http://127.0.0.1:9", S3_BUCKET="test-rx-files",
    S3_ACCESS_KEY="testkey123", S3_SECRET_KEY="test-secret-0123456789abcdef",
)  # fmt: skip

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402
from prescription_service.db import db  # noqa: E402
from prescription_service.main import app  # noqa: E402
from prescription_service.models import ProcessedMessage  # noqa: E402
from prescription_service.services.events import handle_event  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/api/prescription/v1"
TODAY = date(2026, 10, 27)
PP1 = UUID("00000000-0000-0000-0000-0000000000a1")
PP2 = UUID("00000000-0000-0000-0000-0000000000a2")
INTERNAL = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "sales"}


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(recreate_database("test_prescription"))
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean(monkeypatch) -> AsyncIterator[None]:
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 27, 3, 0, tzinfo=UTC))
    async with db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE rx_holds, rx_attachments, rx_items, prescriptions, patient_branches, patient_allergies,"
            " patients, doctors, doc_sequences, branch_settings, known_customers, products, known_branches,"
            " processed_messages, outbox CASCADE"))  # fmt: skip
    redis = connect_redis(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    for bid, code in ((PP1, "PP1"), (PP2, "PP2")):
        await event("branch.created", {"branch_id": str(bid), "code": code, "name_km": "សាខា",
                                       "name_en": f"Branch {code}", "is_active": True})  # fmt: skip
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def event(event_type: str, payload: dict, message_id: UUID | None = None) -> None:
    await process_message(db, ProcessedMessage, handle_event, message_id or uuid4(), event_type, payload)


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,), pharmacist: bool = False) -> dict:
    return {"X-User-Id": str(uuid4()), "X-Role": role, "X-Branch-Ids": ",".join(map(str, branches)),
            "X-Is-Pharmacist": "true" if pharmacist else "false", "X-Permissions": permissions}  # fmt: skip


RX_PERMS = "patients.view,patients.manage,prescriptions.view,prescriptions.manage,prescriptions.override_warning"
OWNER = user("owner", "*", ())
PHARMACIST = user("pharmacist", RX_PERMS, pharmacist=True)
PHARMACIST_PP2 = user("pharmacist", RX_PERMS, (PP2,), pharmacist=True)
CASHIER = user("cashier", "pos.sell,sales.view")


async def add_product(sku: str = "AMOX500", generic: str = "Amoxicillin", classes: tuple[str, ...] = (),
                      ingredients: tuple[str, ...] | None = None, rx: bool = True) -> str:  # fmt: skip
    medicine_id = str(uuid4())
    await event("medicine.created", {
        "medicine_id": medicine_id, "version": 1, "sku": sku, "brand_name": sku.title(), "generic_name": generic,
        "strength": "500mg", "dosage_form": "capsule", "name_km": "ថ្នាំ", "base_unit": "capsule",
        "is_rx_only": rx, "controlled_schedule": None, "is_active": True,
        "active_ingredients": list(ingredients if ingredients is not None else [generic]),
        "drug_classes": list(classes), "pack_units": [],
    })  # fmt: skip
    return medicine_id


async def add_patient(client, headers=PHARMACIST, branch: UUID = PP1, **extra) -> dict:  # noqa: ANN001
    body = {"branch_id": str(branch), "name_en": "Sok Dara", "name_km": "សុខ ដារា", "sex": "female",
            "phone": "012 345 678", **extra}  # fmt: skip
    r = await client.post(f"{PREFIX}/patients", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def add_doctor(client, licence: str = "MD-0001") -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/doctors", json={"name": "Dr Chan", "licence_no": licence, "clinic": "Calmette"},
                          headers=PHARMACIST)  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def add_rx(client, patient: dict, doctor: dict, items: list[dict], *, activate: bool = True,  # noqa: ANN001
                 headers=PHARMACIST, branch: UUID = PP1, **extra) -> dict:  # noqa: ANN001  # fmt: skip
    body = {"branch_id": str(branch), "patient_id": patient["id"], "doctor_id": doctor["id"], "issued_on": "2026-10-25",
            "items": items, **extra}  # fmt: skip
    r = await client.post(f"{PREFIX}/prescriptions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    rx = r.json()
    if activate:
        r = await client.post(f"{PREFIX}/prescriptions/{rx['id']}/activate", headers=headers)
        assert r.status_code == 200, r.text
        rx = r.json()
    return rx


async def hold(client, rx_item_id: str, medicine_id: str, qty: int, *, invoice_id: str | None = None,  # noqa: ANN001
               branch: UUID = PP1, line_no: int = 1, **extra) -> httpx.Response:  # fmt: skip
    body = {"invoice_id": invoice_id or str(uuid4()), "branch_id": str(branch),
            "lines": [{"line_no": line_no, "rx_item_id": rx_item_id, "medicine_id": medicine_id, "qty_base": qty,
                       **extra}]}  # fmt: skip
    return await client.post("/internal/v1/rx/check-and-hold", json=body, headers=INTERNAL)


def invoice_event(invoice_id: str, lines: list[tuple[int, str, int, int]], *, version: int = 1,
                  status: str = "completed") -> dict:  # fmt: skip
    """lines: (line_no, rx_item_id, qty_base, returned_qty_base)."""
    return {"invoice_id": invoice_id, "version": version, "status": status, "branch_id": str(PP1),
            "lines": [{"line_no": n, "rx_item_id": i, "qty_base": q, "returned_qty_base": r}
                      for n, i, q, r in lines]}  # fmt: skip
