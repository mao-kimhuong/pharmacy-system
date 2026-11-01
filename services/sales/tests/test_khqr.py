"""KHQR: create → pending → paid → the sale uses it once; not paid, wrong amount,
used twice, expired, Bakong down; a sale that fails after using it → needs_refund."""

from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError
from sales_service.config import get_settings
from sales_service.db import db
from sales_service.models import KhqrPayment
from sales_service.services import khqr

from .conftest import CASHIER, PP1, PREFIX, SERVICE_TOKEN, line, outbox, receive, sales_event, sell, set_rate
from .test_promotions import stocked


@pytest.fixture(autouse=True)
def shared_account(monkeypatch):
    s = get_settings()
    for k, v in {"khqr_account_id": "pharmacy@aclb", "khqr_merchant_name": "Pharmacy", "khqr_provider": "fake"}.items():
        monkeypatch.setattr(s, k, v)
    khqr.FakeProvider.paid.clear()


async def new_qr(client, amount: str = "0.90", currency: str = "USD", key: str = "qr-key-000001") -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/payments/khqr", json={"branch_id": str(PP1), "amount": amount, "currency": currency},
                          headers={**CASHIER, "Idempotency-Key": key})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def pay_qr(client, qr: dict) -> None:  # noqa: ANN001
    r = await client.post(f"/internal/v1/khqr/fake/{qr['id']}/pay", headers={"X-Service-Token": SERVICE_TOKEN})
    assert r.status_code == 204


def khqr_payment(qr: dict, amount: str | None = None) -> dict:
    return {"method": "KHQR", "currency": qr["currency"], "amount": amount or qr["amount"], "khqr_id": qr["id"]}


def test_emv_crc_and_string() -> None:
    assert khqr.crc16("123456789") == "29B1"  # CRC-16/CCITT-FALSE check value
    s = khqr.khqr_string({"account_id": "pharmacy@aclb", "merchant_name": "Pharmacy", "city": "Phnom Penh"},
                         Decimal("1.50"), "USD", "PP1-1", clock.now() + timedelta(minutes=5))  # fmt: skip
    assert s.startswith("000201010212") and "2917" in s and "5303840" in s and "54041.50" in s
    assert s[-4:] == khqr.crc16(s[:-4])


async def test_paid_qr_pays_the_sale_once(client) -> None:
    para = await stocked()
    await set_rate(client)
    qr = await new_qr(client)
    assert qr["status"] == "pending" and "pharmacy@aclb" in qr["qr_string"]
    r = await sell(client, [line(para, "strip", 1)], [khqr_payment(qr)])
    assert r.status_code == 409 and r.json()["code"] == "KHQR_NOT_PAID"
    await pay_qr(client, qr)
    seen = (await client.get(f"{PREFIX}/payments/khqr/{qr['id']}", headers=CASHIER)).json()
    assert seen["status"] == "paid" and seen["bank_ref"]
    wrong = await sell(client, [line(para, "strip", 1)], [khqr_payment(qr, "0.80"), {"method": "cash", "amount": "0.10"}])
    assert wrong.status_code == 422 and wrong.json()["code"] == "KHQR_MISMATCH"
    r = await sell(client, [line(para, "strip", 1)], [khqr_payment(qr)])
    assert r.status_code == 201, r.text
    used = (await client.get(f"{PREFIX}/payments/khqr/{qr['id']}", headers=CASHIER)).json()
    assert used["status"] == "used" and used["invoice_id"] == r.json()["id"]
    again = await sell(client, [line(para, "strip", 1)], [khqr_payment(qr)])
    assert again.status_code == 409 and again.json()["code"] == "KHQR_USED"


async def test_khr_branch_account_and_expiry(client, monkeypatch) -> None:
    await sales_event("branch.settings_updated", {"branch_id": str(PP1), "khqr": {
        "account_id": "pp1@abaa", "merchant_name": "PP1", "city": "Phnom Penh", "currencies": ["KHR"]}})  # fmt: skip
    qr = await new_qr(client, "4000", "KHR")
    assert "pp1@abaa" in qr["qr_string"] and "5303116" in qr["qr_string"]
    r = await client.post(f"{PREFIX}/payments/khqr", json={"branch_id": str(PP1), "amount": "1.00", "currency": "USD"},
                          headers={**CASHIER, "Idempotency-Key": "qr-key-000002"})  # fmt: skip
    assert r.status_code == 422  # this branch's account takes riel only
    monkeypatch.setattr(clock, "now", lambda: khqr.datetime.fromisoformat(qr["expires_at"]) + timedelta(seconds=1))
    assert (await client.get(f"{PREFIX}/payments/khqr/{qr['id']}", headers=CASHIER)).json()["status"] == "expired"


async def test_bakong_down_is_temporarily_unavailable() -> None:
    down = khqr.BakongProvider(get_settings(), httpx.MockTransport(lambda r: httpx.Response(502)))
    with pytest.raises(AppError) as exc:
        await down.status("abc")
    assert exc.value.code == "TEMPORARILY_UNAVAILABLE"
    paid = khqr.BakongProvider(get_settings(), httpx.MockTransport(lambda r: httpx.Response(
        200, json={"responseCode": 0, "data": {"hash": "h1", "amount": 1.5}})))  # fmt: skip
    assert (await paid.status("abc")).status == "paid"


async def test_a_failed_sale_leaves_the_money_to_refund(client) -> None:
    para = await stocked()
    await set_rate(client)
    qr = await new_qr(client, "48.00")
    await pay_qr(client, qr)
    r = await sell(client, [line(para, "box", 6)], [khqr_payment(qr)])  # only 5 boxes in stock
    assert r.status_code == 409 and r.json()["code"] == "OUT_OF_STOCK"
    async with db.sessionmaker() as s:
        row = (await s.execute(select(KhqrPayment))).scalar_one()
    assert row.status == "needs_refund"
    assert [p["amount"] for t, p in await outbox() if t == "khqr.needs_refund"] == ["48.00"]
    assert receive  # (stock comes from conftest.receive via stocked)


async def test_cancelling_a_khqr_sale_flags_the_refund(client) -> None:
    from .conftest import MANAGER

    para = await stocked()
    await set_rate(client)
    qr = await new_qr(client)
    await pay_qr(client, qr)
    inv = (await sell(client, [line(para, "strip", 1)], [khqr_payment(qr)])).json()
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/cancel", json={"reason": "wrong item"},
                          headers={**MANAGER, "Idempotency-Key": "khqr-cancel-01"})  # fmt: skip
    assert r.status_code == 200, r.text
    assert (await client.get(f"{PREFIX}/payments/khqr/{qr['id']}", headers=CASHIER)).json()["status"] == "needs_refund"
