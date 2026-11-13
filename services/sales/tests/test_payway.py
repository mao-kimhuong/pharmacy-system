"""ABA PayWay KHQR: signing and merchant_auth (a key pair made here, never the real one), the start-up check,
and the whole flow against a fake PayWay that checks every hash: QR → callback → paid; wrong amount → review;
cancel → closed, a late payment → refund due; refunds (PIN, owner / branch manager, once, PTL codes, a timeout);
returns to the KHQR; the daily check."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import SecretStr
from sqlalchemy import select

from pharmacy_shared import clock
from sales_service.config import Settings, get_settings
from sales_service.db import db
from sales_service.models import KhqrPayment, KhqrRefund
from sales_service.services import khqr, payway

from .conftest import (
    AUTH,
    CASHIER,
    MANAGER,
    OWNER,
    PHARMACIST,
    PP1,
    PP2,
    PREFIX,
    idem,
    line,
    outbox,
    sell,
    set_rate,
    user,
)
from .test_promotions import stocked

API_KEY = "test-api-key-0123456789abcdef0123"
MERCHANT = "ec000002"
REFUNDER = user("branch_manager", "pos.sell,sales.view,sales.cancel,sales.return,sales.khqr_refund")
OTHER_BRANCH = user("branch_manager", "pos.sell,sales.view,sales.khqr_refund", (PP2,))


def _h(*parts: str) -> str:
    return base64.b64encode(hmac.new(API_KEY.encode(), "".join(parts).encode(), hashlib.sha512).digest()).decode()


@pytest.fixture(scope="module")
def keys(tmp_path_factory) -> tuple[Any, Path]:  # noqa: ANN001
    private = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pem = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    path = tmp_path_factory.mktemp("keys") / "aba_public.pem"
    path.write_bytes(pem)
    return private, path


class FakePayWay:
    """PayWay's four APIs, checking each hash. `txns[tran_id]` = {amount, currency, status, paid, refunded}."""

    def __init__(self, private: Any) -> None:  # noqa: ANN401
        self.private, self.txns, self.calls = private, {}, []
        self.refund_code: str | None = None  # e.g. "PTL37": the next refund is refused with it
        self.refund_timeout = False  # the next refund goes through but the answer is lost

    def __call__(self, request: httpx.Request) -> httpx.Response:
        b = json.loads(request.content)
        path = request.url.path
        self.calls.append(path.rsplit("/", 1)[-1])
        if path.endswith("/generate-qr"):
            order = ("req_time", "merchant_id", "tran_id", "amount", "items", "first_name", "last_name", "email",
                     "phone", "purchase_type", "payment_option", "callback_url", "return_deeplink", "currency",
                     "custom_fields", "return_params", "payout", "lifetime", "qr_image_template")  # fmt: skip
            text = {k: b.get(k, "") for k in order}
            text["amount"] = payway.amount_text(Decimal(str(b["amount"])))
            if b["hash"] != _h(*(str(text[k]) for k in order)) or b["payment_option"] != "abapay_khqr":
                return httpx.Response(200, json={"status": {"code": "1", "message": "Wrong Hash"}})
            self.txns[b["tran_id"]] = {"amount": Decimal(str(b["amount"])), "currency": b["currency"], "status": 2,
                                       "paid": None, "refunded": Decimal("0")}  # fmt: skip
            return httpx.Response(200, json={"qrString": f"00020101021230510016abaakhppxxx@abaa{b['tran_id']}6304ABCD",
                                             "abapay_deeplink": "abamobilebank://x", "status": {"code": "0"}})  # fmt: skip
        if path.endswith("/check-transaction-2") or path.endswith("/close-transaction"):
            if b["hash"] != _h(b["req_time"], b["merchant_id"], b["tran_id"]):
                return httpx.Response(200, json={"status": {"code": "5", "message": "Invalid hash"}})
            t = self.txns.get(b["tran_id"])
            if t is None:
                return httpx.Response(200, json={"status": {"code": 6 if "check" in path else "5", "message": "not found"}})
            if path.endswith("/close-transaction"):
                if t["status"] == 2:
                    t["status"] = 7
                return httpx.Response(200, json={"status": {"code": "00", "tran_id": b["tran_id"]}})
            paid = t["paid"] or (None, None)
            return httpx.Response(200, json={"data": {
                "payment_status_code": t["status"], "payment_amount": float(paid[0]) if paid[0] else 0,
                "payment_currency": paid[1] or t["currency"], "refund_amount": float(t["refunded"]), "apv": "753786",
                "transaction_date": "2026-10-27 10:00:00"}, "status": {"code": "00", "message": "Success!"}})  # fmt: skip
        if path.endswith("/refund"):
            if b["hash"] != _h(b["request_time"], b["merchant_id"], b["merchant_auth"]):
                return httpx.Response(200, json={"status": {"code": "PTL02", "message": "Wrong Hash"}})
            raw = base64.b64decode(b["merchant_auth"])
            plain = b"".join(self.private.decrypt(raw[i : i + 128], padding.PKCS1v15()) for i in range(0, len(raw), 128))
            auth = json.loads(plain)
            assert auth["mc_id"] == MERCHANT
            if self.refund_code:
                code, self.refund_code = self.refund_code, None
                return httpx.Response(200, json={"status": {"code": code, "message": "refused"}})
            t = self.txns[auth["tran_id"]]
            t["refunded"] += Decimal(str(auth["refund_amount"]))
            t["status"] = 4
            if self.refund_timeout:
                self.refund_timeout = False
                raise httpx.ReadTimeout("lost", request=request)
            return httpx.Response(200, json={"grand_total": float(t["amount"]), "total_refunded": float(t["refunded"]),
                                             "currency": t["currency"], "transaction_status": "REFUNDED",
                                             "status": {"code": "00", "message": "Success!"}})  # fmt: skip
        return httpx.Response(404)

    def pay(self, tran_id: str, amount: str | None = None, currency: str | None = None) -> None:
        t = self.txns[tran_id]
        t["status"], t["paid"] = 0, (Decimal(amount) if amount else t["amount"], currency or t["currency"])


@pytest.fixture
def pw(monkeypatch, keys) -> FakePayWay:  # noqa: ANN001
    private, path = keys
    fake = FakePayWay(private)
    s = get_settings()
    for k, v in {"khqr_provider": "payway", "payway_base_url": "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/purchase",
                 "payway_merchant_id": MERCHANT, "payway_api_key": SecretStr(API_KEY),
                 "payway_rsa_public_key_file": str(path)}.items():  # fmt: skip
        monkeypatch.setattr(s, k, v)
    transport = httpx.MockTransport(fake)

    def make(settings: Settings | None = None, name: str | None = None) -> khqr.Provider:
        name = name or s.khqr_provider
        return khqr.PayWayProvider(s, transport) if name == "payway" else khqr.FakeProvider()

    monkeypatch.setattr(khqr, "provider", make)
    return fake


async def new_qr(client, amount: str = "0.90", currency: str = "USD") -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/payments/khqr", json={"branch_id": str(PP1), "amount": amount, "currency": currency},
                          headers={**CASHIER, **idem()})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def callback(client, tran_id: str) -> None:  # noqa: ANN001
    # what PayWay sends (unsigned): only tran_id is read; "status": "0" here proves nothing by itself
    r = await client.post(f"{PREFIX}/payments/payway/callback", json={"tran_id": tran_id, "status": "0", "apv": "1"})
    assert r.status_code == 200 and r.json() == {"received": True}


async def qr_status(client, qr: dict) -> dict:  # noqa: ANN001
    return (await client.get(f"{PREFIX}/payments/khqr/{qr['id']}", headers=CASHIER)).json()


def pin(headers: dict, branch=PP1) -> str:  # noqa: ANN001
    return AUTH.issue(headers["X-User-Id"], khqr.REFUND_PIN_ACTION, branches=(branch,))


async def refunds(client, status: str | None = None) -> list[dict]:  # noqa: ANN001
    r = await client.get(f"{PREFIX}/payments/khqr/refunds", params={"status": status} if status else {},
                         headers=REFUNDER)  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


async def do_refund(client, refund_id: str, headers: dict | None = None, token: str | None = "auto"):  # noqa: ANN001, ANN201
    headers = headers or REFUNDER
    body = {"pin_token": pin(headers) if token == "auto" else token}
    return await client.post(f"{PREFIX}/payments/khqr/refunds/{refund_id}/refund", json=body, headers={**headers, **idem()})


# ---------------------------------------------------------------- pure parts


def test_hash_merchant_auth_and_amounts(keys) -> None:  # noqa: ANN001
    private, path = keys
    assert payway.sign(API_KEY, "20250213065545", MERCHANT, "17394277693") == _h("20250213065545", MERCHANT, "17394277693")
    public = payway.load_public_key(str(path))
    long_merchant = "m" * 120  # > 117 bytes of JSON: two RSA chunks
    raw = base64.b64decode(payway.merchant_auth(public, long_merchant, "K1", Decimal("1.50")))
    assert len(raw) == 256
    plain = b"".join(private.decrypt(raw[i : i + 128], padding.PKCS1v15()) for i in (0, 128))
    assert json.loads(plain) == {"mc_id": long_merchant, "tran_id": "K1", "refund_amount": 1.5}
    assert [payway.amount_text(Decimal(x)) for x in ("1.50", "0.01", "4000", "4000.00", "12.30")] == [
        "1.5", "0.01", "4000", "4000", "12.3"]  # fmt: skip
    assert payway.req_time(datetime(2026, 10, 27, 3, 4, 5, tzinfo=UTC)) == "20261027030405"


def test_base_url_status_codes_and_pem_without_headers(keys, tmp_path) -> None:  # noqa: ANN001
    for url in ("https://checkout-sandbox.payway.com.kh", "https://checkout-sandbox.payway.com.kh/",
                "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/purchase"):
        assert payway.api_root(url) == "https://checkout-sandbox.payway.com.kh"
    assert payway.api_root("https://proxy.example.com/payway/api/x") == "https://proxy.example.com/payway"
    with pytest.raises(ValueError):
        payway.api_root("checkout.payway.com.kh")
    assert payway.status_code({"status": {"code": 0}}) == "00"
    assert payway.status_code({"data": {"status": {"code": "00"}}}) == "00"
    assert payway.status_code({"status": {"code": 6}}) == "6"
    assert payway.status_code({"status": {"code": "PTL37"}}) == "PTL37"
    bare = tmp_path / "bare.pem"
    lines = keys[1].read_text().strip().splitlines()[1:-1]
    bare.write_text("".join(lines))  # one line of base64, no BEGIN/END (as ABA's portal shows it)
    assert payway.load_public_key(str(bare)).key_size == 1024


def test_start_up_check_names_the_setting_never_its_value(keys, tmp_path) -> None:  # noqa: ANN001
    secret = "very-secret-api-key-value-123456"
    base = {"khqr_provider": "payway", "payway_base_url": "https://checkout-sandbox.payway.com.kh",
            "payway_merchant_id": MERCHANT, "payway_api_key": SecretStr(secret),
            "payway_rsa_public_key_file": str(keys[1])}  # fmt: skip
    Settings(**base).check_khqr()  # all there: fine
    cases = {
        "payway_merchant_id": ("", "PAYWAY_MERCHANT_ID"),
        "payway_api_key": (SecretStr(""), "PAYWAY_API_KEY"),
        "payway_rsa_public_key_file": (str(tmp_path / "nope.pem"), "PAYWAY_RSA_PUBLIC_KEY_FILE cannot be read"),
        "payway_base_url": ("checkout.payway.com.kh", "PAYWAY_BASE_URL is not an http(s) URL"),
    }
    for field, (value, expected) in cases.items():
        with pytest.raises(RuntimeError) as exc:
            Settings(**{**base, field: value}).check_khqr()
        assert expected in str(exc.value) and secret not in str(exc.value) and MERCHANT not in str(exc.value)
    junk = tmp_path / "junk.pem"
    junk.write_text("not set: placeholder")
    with pytest.raises(RuntimeError, match="not an RSA public key"):
        Settings(**{**base, "payway_rsa_public_key_file": str(junk)}).check_khqr()
    with pytest.raises(RuntimeError, match="PAYWAY_RSA_PRIVATE_KEY_FILE cannot be read"):
        Settings(**{**base, "payway_rsa_private_key_file": str(tmp_path / "gone.pem")}).check_khqr()
    with pytest.raises(RuntimeError, match="fake, bakong or payway"):
        Settings(khqr_provider="paypal").check_khqr()
    assert secret not in repr(Settings(**base)) and secret not in str(Settings(**base).model_dump())


# ---------------------------------------------------------------- the flow


async def test_qr_paid_after_the_callback_and_used_by_the_sale(client, pw) -> None:
    para = await stocked()
    await set_rate(client)
    qr = await new_qr(client)
    assert qr["provider"] == "payway" and len(qr["tran_id"]) <= 20 and qr["qr_string"].endswith("ABCD")
    assert pw.calls == ["generate-qr"]
    await callback(client, qr["tran_id"])  # PayWay says "0" but nothing was paid: still pending
    assert (await qr_status(client, qr))["status"] == "pending"
    await callback(client, "K-unknown-0001")  # unknown: the same answer, nothing happens
    await callback(client, "'; DROP TABLE x;--")  # malformed: not even looked up
    pw.pay(qr["tran_id"])
    await callback(client, qr["tran_id"])
    seen = await qr_status(client, qr)
    assert seen["status"] == "paid" and seen["bank_ref"] == "753786" and seen["paid_currency"] == "USD"
    await callback(client, qr["tran_id"])  # again: idempotent
    r = await sell(client, [line(para, "strip", 1)], [{"method": "KHQR", "currency": "USD", "amount": "0.90",
                                                        "khqr_id": qr["id"]}])  # fmt: skip
    assert r.status_code == 201, r.text
    assert (await qr_status(client, qr))["status"] == "used"


async def test_a_wrong_amount_is_flagged_for_a_manager_not_taken(client, pw) -> None:
    para = await stocked()
    await set_rate(client)
    qr = await new_qr(client, "0.90")
    pw.pay(qr["tran_id"], "0.50")
    seen = await qr_status(client, qr)
    assert seen["status"] == "review" and "Paid 0.50 USD" in seen["review_reason"]
    assert [p["paid_amount"] for t, p in await outbox() if t == "khqr.review"] == ["0.50"]
    r = await sell(client, [line(para, "strip", 1)], [{"method": "KHQR", "currency": "USD", "amount": "0.90",
                                                        "khqr_id": qr["id"]}])  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "KHQR_MISMATCH"
    due = await refunds(client, "due")
    assert [(x["source"], x["amount"]) for x in due] == [("review", "0.50")]


async def test_cancel_closes_it_and_a_late_payment_is_due_back(client, pw, monkeypatch) -> None:
    qr = await new_qr(client)
    r = await client.post(f"{PREFIX}/payments/khqr/{qr['id']}/cancel", headers=CASHIER)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert "close-transaction" in pw.calls and pw.txns[qr["tran_id"]]["status"] == 7
    again = await client.post(f"{PREFIX}/payments/khqr/{qr['id']}/cancel", headers=CASHIER)
    assert again.status_code == 200  # idempotent
    pw.pay(qr["tran_id"])  # it slipped through anyway
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 10, 27, 3, 2, tzinfo=UTC))
    async with db.sessionmaker() as s:
        await khqr.poll_pending(s)
    assert (await qr_status(client, qr))["status"] == "needs_refund"
    assert [(x["source"], x["amount"]) for x in await refunds(client, "due")] == [("late_payment", "0.90")]
    paid = await new_qr(client)
    pw.pay(paid["tran_id"])
    r = await client.post(f"{PREFIX}/payments/khqr/{paid['id']}/cancel", headers=CASHIER)
    assert r.status_code == 409 and r.json()["code"] == "KHQR_STATE"


async def test_an_expired_qr_is_closed_at_payway(client, pw, monkeypatch) -> None:
    qr = await new_qr(client)
    later = datetime.fromisoformat(qr["expires_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(clock, "now", lambda: later)
    assert (await qr_status(client, qr))["status"] == "expired"
    assert pw.txns[qr["tran_id"]]["status"] == 7


async def test_refund_after_a_failed_sale_pin_permissions_and_once(client, pw) -> None:
    para = await stocked()
    await set_rate(client)
    qr = await new_qr(client, "48.00")
    pw.pay(qr["tran_id"])
    r = await sell(client, [line(para, "box", 6)], [{"method": "KHQR", "currency": "USD", "amount": "48.00",
                                                      "khqr_id": qr["id"]}])  # only 5 boxes  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "OUT_OF_STOCK"
    [due] = await refunds(client, "due")
    assert due["source"] == "failed_sale" and due["amount"] == "48.00" and due["payment"]["status"] == "needs_refund"
    cashier = await client.post(f"{PREFIX}/payments/khqr/refunds/{due['id']}/refund", json={}, headers={**CASHIER, **idem()})
    assert cashier.status_code == 403
    for who in (PHARMACIST,):
        assert (await client.get(f"{PREFIX}/payments/khqr/refunds", headers=who)).status_code == 403
    other = await do_refund(client, due["id"], OTHER_BRANCH)
    assert other.status_code == 404  # another branch's refund is not seen
    no_pin = await do_refund(client, due["id"], token=None)
    assert no_pin.status_code == 401 and no_pin.json()["code"] == "PIN_REQUIRED"
    assert "refund" not in pw.calls
    done = await do_refund(client, due["id"])
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "refunded" and body["method"] == "payway" and body["payment"]["status"] == "refunded"
    assert pw.txns[qr["tran_id"]]["refunded"] == Decimal("48")
    again = await do_refund(client, due["id"])  # a second press: the same refund, PayWay not asked again
    assert again.status_code == 200 and pw.calls.count("refund") == 1
    owner = await do_refund(client, due["id"], OWNER)
    assert owner.status_code == 200 and pw.calls.count("refund") == 1
    events = [p for t, p in await outbox() if t == "khqr.refunded"]
    assert len(events) == 1 and events[0]["method"] == "payway" and events[0]["amount"] == "48.00"


async def test_payway_refusals_are_mapped_and_the_refund_stays_due(client, pw) -> None:
    from .test_khqr import khqr_payment  # noqa: F401 – same payment shape

    para = await stocked()
    await set_rate(client)
    qr = await new_qr(client, "0.90")
    pw.pay(qr["tran_id"])
    inv = (await sell(client, [line(para, "strip", 1)], [{"method": "KHQR", "currency": "USD", "amount": "0.90",
                                                           "khqr_id": qr["id"]}])).json()  # fmt: skip
    r = await client.post(f"{PREFIX}/invoices/{inv['id']}/cancel", json={"reason": "wrong item"},
                          headers={**MANAGER, **idem()})  # fmt: skip
    assert r.status_code == 200, r.text
    [due] = await refunds(client, "due")
    assert due["source"] == "invoice_cancel"
    for code, ours, status in (("PTL37", "KHQR_REFUND_TOO_MUCH", 422), ("PTL181", "KHQR_REFUND_NO_BALANCE", 409),
                               ("PTL168", "KHQR_REFUND_BUSY", 409), ("PTL02", "PAYWAY_AUTH_FAILED", 502),
                               ("PTL58", "PAYWAY_REJECTED", 502)):  # fmt: skip
        pw.refund_code = code
        r = await do_refund(client, due["id"])
        assert (r.status_code, r.json()["code"]) == (status, ours), code
        [again] = await refunds(client, "due")
        assert again["last_error"] == ours
    assert pw.txns[qr["tran_id"]]["refunded"] == 0
    pw.refund_timeout = True  # PayWay refunds but the answer is lost
    lost = await do_refund(client, due["id"])
    assert lost.status_code == 503
    assert (await refunds(client, "requested"))[0]["id"] == due["id"]
    retry = await do_refund(client, due["id"])  # asks PayWay first: already refunded → not refunded twice
    assert retry.status_code == 200 and retry.json()["status"] == "refunded"
    assert pw.txns[qr["tran_id"]]["refunded"] == Decimal("0.9") and pw.calls.count("refund") == 6


async def test_a_return_can_go_back_to_the_khqr(client, pw) -> None:
    para = await stocked()
    await set_rate(client, 4100)
    qr = await new_qr(client, "11100", "KHR")  # 3 strips: 2.70 USD = 11 070 → 11 100 riel (the invoice's total_khr)
    pw.pay(qr["tran_id"])
    sale = await sell(client, [line(para, "strip", 3)],
                      [{"method": "KHQR", "currency": "KHR", "amount": "11100", "khqr_id": qr["id"]}])  # fmt: skip
    assert sale.status_code == 201, sale.text
    inv = sale.json()

    async def give_back(qty: int):  # noqa: ANN202
        body = {"lines": [{"invoice_line_id": inv["lines"][0]["id"], "qty": qty}], "refund_method": "khqr",
                "reason": "not needed", "to": "stock"}  # fmt: skip
        return await client.post(f"{PREFIX}/invoices/{inv['id']}/returns", json=body, headers={**PHARMACIST, **idem()})

    r = await give_back(1)
    assert r.status_code == 201, r.text
    [due] = await refunds(client, "due")
    assert due["source"] == "return" and due["currency"] == "KHR" and due["amount"] == "3700.00"  # 0.90 × 4100 = 3 690 → 3 700
    assert (await do_refund(client, due["id"])).status_code == 200
    assert pw.txns[qr["tran_id"]]["refunded"] == Decimal("3700")
    r = await give_back(2)  # 1.80 USD = 7 380 → 7 400 riel: exactly what is left on the QR
    assert r.status_code == 201, r.text
    assert [x["amount"] for x in await refunds(client, "due")] == ["7400.00"]
    assert (await qr_status(client, qr))["status"] == "used"  # a sale still keeps it until all is back


async def test_bakong_refund_is_recorded_as_done_by_hand(client, monkeypatch) -> None:
    s = get_settings()
    for k, v in {"khqr_account_id": "pharmacy@aclb", "khqr_merchant_name": "Pharmacy", "khqr_provider": "fake"}.items():
        monkeypatch.setattr(s, k, v)
    qr = await new_qr(client)
    async with db.sessionmaker() as session:
        p = await session.get(KhqrPayment, qr["id"])
        p.provider, p.status, p.paid_amount = "bakong", "used", Decimal("0.90")
        khqr.needs_refund(session, p, "Sale failed")
        await session.commit()
    [due] = await refunds(client, "due")
    r = await do_refund(client, due["id"])
    assert r.status_code == 200 and r.json()["method"] == "by_hand"
    texts = [p for t, p in await outbox() if t == "khqr.needs_refund"]
    assert texts[0]["provider"] == "bakong"


async def test_daily_check_lists_what_does_not_agree_once(client, pw) -> None:
    unused = await new_qr(client)
    pw.pay(unused["tran_id"])
    assert (await qr_status(client, unused))["status"] == "paid"  # paid, and no sale took it
    lost = await new_qr(client)
    async with db.sessionmaker() as s:  # recorded paid, but PayWay never saw the money
        p = await s.get(KhqrPayment, lost["id"])
        p.status, p.paid_amount = "paid", p.amount
        await s.commit()
    async with db.sessionmaker() as s:
        first = await khqr.reconcile(s, clock.today())
    async with db.sessionmaker() as s:
        second = await khqr.reconcile(s, clock.today())
    assert first["checked"] == 2 and first["issues"] == 3 and second["issues"] == 0
    r = await client.get(f"{PREFIX}/payments/khqr/reconciliation", params={"date": clock.today().isoformat()},
                         headers=REFUNDER)  # fmt: skip
    kinds = sorted((x["khqr_id"] == unused["id"], x["kind"]) for x in r.json())
    assert kinds == [(False, "not_paid_at_provider"), (False, "paid_not_used"), (True, "paid_not_used")]
    assert (await client.get(f"{PREFIX}/payments/khqr/reconciliation", headers=CASHIER)).status_code == 403
    [event] = [p for t, p in await outbox() if t == "khqr.reconciled"]
    assert event["issues"] == 3 and event["kinds"] == {"not_paid_at_provider": 1, "paid_not_used": 2}
    async with db.sessionmaker() as s:
        assert (await s.execute(select(KhqrRefund))).first() is None  # a check never refunds anything
