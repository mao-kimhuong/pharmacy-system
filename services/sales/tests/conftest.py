"""Sales tests run the sale saga against the REAL inventory, customers and prescription apps
(over ASGI, each with its own test database), so FEFO, row locks, credit limits
and compensations are the production code paths. Real Postgres + Redis."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.redis import connect as connect_redis
from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

SERVICE_TOKEN = "test-service-token-0123456789abcdef"
os.environ.update(
    DATABASE_URL=test_database_url("test_sales"), REDIS_URL=TEST_REDIS_URL, OUTBOX_RELAY_ENABLED="false",
    EVENT_CONSUMER_ENABLED="false", RECOVERY_ENABLED="false", EXPIRY_JOB_ENABLED="false",
    SERVICE_TOKEN=SERVICE_TOKEN,
)  # fmt: skip

# The other services get their own databases: set before their apps are built.
import customers_service.config as customers_config  # noqa: E402
import inventory_service.config as inventory_config  # noqa: E402
import prescription_service.config as prescription_config  # noqa: E402

inventory_config.get_settings().database_url = test_database_url("test_sales_inventory")
customers_config.get_settings().database_url = test_database_url("test_sales_customers")
prescription_config.get_settings().database_url = test_database_url("test_sales_prescription")
prescription_config.get_settings().storage_bucket_check = False

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

import customers_service.main as customers_main  # noqa: E402
import inventory_service.main as inventory_main  # noqa: E402
import prescription_service.main as prescription_main  # noqa: E402
from customers_service.db import db as customers_db  # noqa: E402
from customers_service.models import ProcessedMessage as CustomersProcessed  # noqa: E402
from customers_service.services.events import handle_event as customers_handle  # noqa: E402
from inventory_service.db import db as inventory_db  # noqa: E402
from inventory_service.models import ProcessedMessage as InventoryProcessed  # noqa: E402
from inventory_service.services.events import handle_event as inventory_handle  # noqa: E402
from pharmacy_shared import clock  # noqa: E402
from pharmacy_shared.consumer import process_message  # noqa: E402
from pharmacy_shared.internal import InternalClient  # noqa: E402
from prescription_service.db import db as prescription_db  # noqa: E402
from prescription_service.models import ProcessedMessage as PrescriptionProcessed  # noqa: E402
from prescription_service.services.events import handle_event as prescription_handle  # noqa: E402
from sales_service.db import db  # noqa: E402
from sales_service.main import app  # noqa: E402
from sales_service.models import OutboxEvent, ProcessedMessage  # noqa: E402
from sales_service.services.clients import Clients, get_clients  # noqa: E402
from sales_service.services.events import handle_event  # noqa: E402

from .fake_auth import FakeAuth  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "/api/sales/v1"
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
    _migrate("sales", test_database_url("test_sales"))
    _migrate("inventory", inventory_config.get_settings().database_url)
    _migrate("customers", customers_config.get_settings().database_url)
    _migrate("prescription", prescription_config.get_settings().database_url)


AUTH = FakeAuth()


def real_clients(**override) -> Clients:
    def client(asgi_app) -> InternalClient:  # noqa: ANN001
        return InternalClient(
            "http://svc", "sales", SERVICE_TOKEN, transport=httpx.ASGITransport(app=asgi_app)
        )

    return Clients(inventory=override.get("inventory") or client(inventory_main.app),
                   customers=override.get("customers") or client(customers_main.app),
                   prescription=override.get("prescription") or client(prescription_main.app),
                   auth=override.get("auth") or AUTH)  # fmt: skip


@pytest.fixture(autouse=True)
async def clean(monkeypatch) -> AsyncIterator[None]:
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 27, 3, 0, tzinfo=UTC))  # 10:00 in Phnom Penh
    async with db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE sale_return_lines, sale_returns, invoice_line_batches, invoice_payments, invoice_lines, invoices,"
            " exchange_rates, doc_sequences, branch_settings, known_customers, product_pack_units, products,"
            " known_branches, processed_messages, outbox, promotion_uses, promotions, suspended_carts,"
            " sale_template_lines, sale_templates, sale_order_lines, sale_orders, commission_lines,"
            " commission_periods, commission_rules, khqr_payments CASCADE"))  # fmt: skip
    async with inventory_db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE reservation_lines, reservations, quarantine_entries, movements, stock, batches, stock_ins,"
            " product_pack_units, products, known_branches, known_suppliers, processed_messages, outbox CASCADE"))  # fmt: skip
    async with customers_db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE customer_allocations, customer_payments, customer_debts, ledger_entries, customers,"
            " customer_groups, doc_sequences, known_branches, processed_messages, outbox, deposit_movements,"
            " deposits CASCADE"))  # fmt: skip
    async with prescription_db.engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE rx_holds, rx_attachments, rx_items, prescriptions, patient_branches, patient_allergies,"
            " patients, doctors, doc_sequences, branch_settings, known_customers, products, known_branches,"
            " processed_messages, outbox CASCADE"))  # fmt: skip
    redis = connect_redis(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    for bid, code in ((PP1, "PP1"), (PP2, "PP2")):
        await everywhere("branch.created", {"branch_id": str(bid), "code": code, "name_km": "សាខា",
                                            "name_en": f"Branch {code}", "is_active": True})  # fmt: skip
    await sales_event("branch.settings_updated", {"branch_id": str(PP1), "receipt_header": "Tel 012 000 111",
                                                  "receipt_footer": "Thank you", "allow_opened_pack_returns": False})  # fmt: skip
    app.dependency_overrides[get_clients] = lambda: real_clients()
    yield
    app.dependency_overrides.clear()
    for d in (db, inventory_db, customers_db, prescription_db):
        await d.dispose()
    for a in (app, inventory_main.app, customers_main.app, prescription_main.app):
        await a.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def customers_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=customers_main.app), base_url="http://test"
    ) as c:
        yield c


async def sales_event(event_type: str, payload: dict) -> None:
    await process_message(db, ProcessedMessage, handle_event, uuid4(), event_type, payload)


async def inventory_event(event_type: str, payload: dict) -> None:
    await process_message(inventory_db, InventoryProcessed, inventory_handle, uuid4(), event_type, payload)


async def everywhere(event_type: str, payload: dict) -> None:
    await sales_event(event_type, payload)
    await inventory_event(event_type, payload)
    await process_message(customers_db, CustomersProcessed, customers_handle, uuid4(), event_type, payload)
    await prescription_event(event_type, payload)


async def prescription_event(event_type: str, payload: dict, message_id: UUID | None = None) -> None:
    await process_message(prescription_db, PrescriptionProcessed, prescription_handle, message_id or uuid4(),
                          event_type, payload)  # fmt: skip


async def relay_invoices() -> None:
    """invoice.* events from the sales outbox to the prescription service, with the
    outbox id as message id (like the relay: a second run delivers nothing new)."""
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.event_type.like("invoice.%"))
                                .order_by(OutboxEvent.seq))).scalars().all()  # fmt: skip
    for row in rows:
        await prescription_event(row.event_type, row.payload, row.id)


def user(role: str, permissions: str, branches: tuple[UUID, ...] = (PP1,), pharmacist: bool = False) -> dict:
    return {"X-User-Id": str(uuid4()), "X-Role": role, "X-Branch-Ids": ",".join(map(str, branches)),
            "X-Is-Pharmacist": "true" if pharmacist else "false", "X-Permissions": permissions}  # fmt: skip


OWNER = user("owner", "*", ())
MANAGER = user("branch_manager", "pos.sell,sales.view,sales.cancel,sales.cancel_any,sales.return,sales.exchange_rate,"
               "contacts.customers,customers.credit_limit")  # fmt: skip
PHARMACIST = user("pharmacist", "pos.sell,sales.view,sales.cancel,sales.return", pharmacist=True)
CASHIER = user("cashier", "pos.sell,sales.view,contacts.customers")


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


async def add_product(sku: str = "PARA500", *, rx: bool = False, controlled: str | None = None,
                      prices=("0.10", "0.90", "8.00"), ingredients: tuple[str, ...] = (),
                      classes: tuple[str, ...] = (), category: str | None = None) -> dict:  # fmt: skip
    """tablet / strip (10) / box (100) with sell prices; known to sales and inventory."""
    medicine_id = uuid4()
    units = [("tablet", 1, prices[0]), ("strip", 10, prices[1]), ("box", 100, prices[2])]
    ids = {n: uuid4() for n, _, _ in units}
    await everywhere("medicine.created", {
        "medicine_id": str(medicine_id), "version": 1, "sku": sku, "brand_name": sku.title(),
        "generic_name": "Generic", "strength": "500mg", "dosage_form": "tablet", "name_km": "ថ្នាំ",
        "base_unit": "tablet", "is_rx_only": rx or bool(controlled), "controlled_schedule": controlled,
        "is_active": True, "active_ingredients": list(ingredients), "drug_classes": list(classes),
        "category": {"id": category, "name_en": "Cat", "name_km": ""} if category else None,
        "pack_units": [{"id": str(ids[n]), "name": n, "qty_in_base": q, "barcode": None, "sell_price": p,
                        "is_base": q == 1, "is_active": True} for n, q, p in units],
    })  # fmt: skip
    return {"id": str(medicine_id), **{n: str(i) for n, i in ids.items()}}


async def receive(product: dict, lots: list[tuple[str, str, int]], branch: UUID = PP1) -> None:
    """Stock in inventory, as goods.received from purchasing: (lot, expiry, qty_base)."""
    await inventory_event("goods.received", {
        "receipt_id": str(uuid4()), "number": "PP1-GRN-2026-000001", "po_id": str(uuid4()),
        "po_number": "PP1-PO-2026-000001", "branch_id": str(branch), "supplier_id": str(SUPPLIER),
        "received_at": "2026-10-01T03:00:00+00:00", "received_by": None,
        "lines": [{"receipt_line_id": str(uuid4()), "medicine_id": product["id"], "pack_unit_id": product["box"],
                   "qty_base": qty, "lot_no": lot, "expiry_date": exp, "cost_per_base": "0.0400",
                   "controlled_schedule": None, "is_controlled": False} for lot, exp, qty in lots]})  # fmt: skip


async def set_rate(client, rate: int = 4100, branch: UUID = PP1) -> None:
    r = await client.put(f"{PREFIX}/exchange-rates/{branch}", json={"khr_per_usd": rate}, headers=MANAGER)
    assert r.status_code == 200, r.text


def line(product: dict, pack: str, qty: int, **extra) -> dict:
    return {"medicine_id": product["id"], "pack_unit_id": product[pack], "qty": qty, **extra}


def pay(amount: str, currency: str = "USD", method: str = "cash") -> dict:
    return {"method": method, "currency": currency, "amount": amount}


async def sell(
    client, lines: list[dict], payments: list[dict], headers=None, key: dict | None = None, **extra
):
    body = {"branch_id": str(PP1), "lines": lines, "payments": payments, **extra}
    return await client.post(
        f"{PREFIX}/invoices", json=body, headers={**(headers or CASHIER), **(key or idem())}
    )


async def inventory_stock(product: dict) -> dict[str, tuple[int, int, int]]:
    """lot → (on hand, reserved, quarantined) at PP1."""
    async with inventory_db.engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT b.lot_no, s.qty_on_hand, s.qty_reserved, s.qty_quarantined FROM stock s JOIN batches b "
            "ON b.id = s.batch_id WHERE b.medicine_id = :m AND s.branch_id = :b ORDER BY b.expiry_date"),
            {"m": product["id"], "b": PP1})  # fmt: skip
        return {r[0]: (r[1], r[2], r[3]) for r in rows}


async def outbox() -> list[tuple[str, dict]]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT event_type, payload FROM outbox ORDER BY seq"))
        return [(r[0], r[1] if isinstance(r[1], dict) else json.loads(r[1])) for r in rows]


async def audits() -> list[dict]:
    return [p for t, p in await outbox() if t == "audit.recorded"]


async def make_customer(customers_client, limit: str = "20.00") -> dict:
    r = await customers_client.post("/api/customers/v1/customers", headers=OWNER,
                                    json={"phone": f"012{uuid4().int % 1000000:06d}", "name": "Sok Dara",
                                          "credit_limit": limit})  # fmt: skip
    assert r.status_code == 201, r.text
    c = r.json()
    await sales_event("customer.created", {"customer_id": c["id"], "phone": c["phone"], "name": c["name"],
                                           "name_km": "", "group_id": None, "credit_limit": limit, "is_active": True})  # fmt: skip
    return c


async def customer_balance(customers_client, customer: dict) -> Decimal:
    r = await customers_client.get(f"/api/customers/v1/customers/{customer['id']}", headers=OWNER)
    return Decimal(r.json()["balance"])
