"""PayWay Purchase (hosted checkout) at the till: the signed form (hash in docs/payway/purchase.md's order, with the
docs' sample values), then purchase → pending → paid by check-transaction (the callback only triggers it), a sale
with method PAYWAY; cancel; a wrong amount → review; a duplicate callback changes nothing; refund like KHQR.
The sandbox test runs only with PAYWAY_SANDBOX_TEST=1 and the real settings in the environment (never printed)."""

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from sales_service.config import get_settings
from sales_service.services import payway

from .conftest import CASHIER, OWNER, PP1, PREFIX, idem, line, outbox, sell, set_rate
from .test_payway import API_KEY, MERCHANT, REFUNDER, callback, do_refund, keys, pw, qr_status, refunds  # noqa: F401
from .test_promotions import stocked

SAMPLE = {"req_time": "20250213065545", "merchant_id": "ec000002", "tran_id": "17394277693"}  # docs' sample


def test_hash_follows_the_documented_order_with_the_docs_sample_values() -> None:
    at = datetime(2025, 2, 13, 6, 55, 45, tzinfo=UTC)
    f = payway.purchase_form(API_KEY, SAMPLE["merchant_id"], SAMPLE["tran_id"], Decimal("0.10"), "USD",
                             return_url="https://shop.example/api/sales/v1/payments/payway/callback",
                             cancel_url="https://shop.example/pos/payway-return?result=cancel",
                             continue_success_url="https://shop.example/pos/payway-return?result=done",
                             payment_option="cards", lifetime=15, at=at)  # fmt: skip
    assert f["req_time"] == SAMPLE["req_time"] and f["amount"] == "0.1" and f["type"] == "purchase"
    assert base64.b64decode(f["return_url"]).decode().endswith("/payments/payway/callback")  # base64 as documented
    # $req_time . $merchant_id . $tran_id . $amount . $items . $shipping . $firstname . $lastname . $email . $phone .
    # $type . $payment_option . $return_url . $cancel_url . $continue_success_url . $return_deeplink . $currency .
    # $custom_fields . $return_params . $payout . $lifetime . $additional_params . $google_pay_token . $skip_success_page
    b4hash = ("20250213065545" + "ec000002" + "17394277693" + "0.1" + "" + "" + "" + "" + "" + "" + "purchase" + "cards"
              + f["return_url"] + f["cancel_url"] + f["continue_success_url"] + "" + "USD" + "" + "" + "" + "15" + "" + ""
              + "1")  # fmt: skip
    expected = base64.b64encode(hmac.new(API_KEY.encode(), b4hash.encode(), hashlib.sha512).digest()).decode()
    assert f["hash"] == expected
    assert f["view_type"] == "hosted_view" and f["payment_gate"] == "0"  # sent, not hashed (not in the docs' list)
    assert "shipping" not in f and "items" not in f  # empty ones are not sent (and hash as empty text)


async def new_checkout(client, amount: str = "0.90", option: str | None = "cards") -> dict:  # noqa: ANN001
    body = {"branch_id": str(PP1), "amount": amount, "currency": "USD", **({"payment_option": option} if option else {})}
    r = await client.post(f"{PREFIX}/payments/payway/checkout", json=body, headers={**CASHIER, **idem()})
    assert r.status_code == 201, r.text
    return r.json()


def checkout_payment(c: dict, amount: str | None = None) -> dict:
    p = c["payment"]
    return {"method": "PAYWAY", "currency": p["currency"], "amount": amount or p["amount"], "khqr_id": p["id"]}


async def test_purchase_pending_then_paid_then_the_sale(client, pw) -> None:  # noqa: ANN001, F811
    para = await stocked()
    await set_rate(client)
    c = await new_checkout(client)
    form, p = c["form"], c["payment"]
    assert p["kind"] == "checkout" and p["status"] == "pending" and len(p["tran_id"]) <= 20
    assert form["action"] == "https://checkout-sandbox.payway.com.kh/api/payment-gateway/v1/payments/purchase"
    assert form["fields"]["tran_id"] == p["tran_id"] and form["fields"]["payment_option"] == "cards"
    assert form["fields"]["continue_success_url"].startswith(get_settings().payway_web_url)
    assert API_KEY not in str(c)  # the form carries the hash, never the key
    pw.txns[p["tran_id"]] = {"amount": Decimal("0.90"), "currency": "USD", "status": 2, "paid": None,
                             "refunded": Decimal("0")}  # the browser posted the form: PayWay knows it  # fmt: skip
    r = await sell(client, [line(para, "strip", 1)], [checkout_payment(c)])
    assert r.status_code == 409 and r.json()["code"] == "KHQR_NOT_PAID"
    pw.pay(p["tran_id"])
    await callback(client, p["tran_id"])
    await callback(client, p["tran_id"])  # PayWay pushes twice: nothing changes the second time
    assert (await qr_status(client, p))["status"] == "paid"
    r = await sell(client, [line(para, "strip", 1)], [checkout_payment(c)])
    assert r.status_code == 201, r.text
    assert r.json()["payments"][0]["method"] == "PAYWAY"
    assert (await qr_status(client, p))["status"] == "used"
    again = await sell(client, [line(para, "strip", 1)], [checkout_payment(c)])
    assert again.status_code == 409 and again.json()["code"] == "KHQR_USED"


async def test_a_checkout_and_a_qr_are_not_interchangeable(client, pw) -> None:  # noqa: ANN001, F811
    para = await stocked()
    await set_rate(client)
    c = await new_checkout(client)
    r = await sell(client, [line(para, "strip", 1)], [{**checkout_payment(c), "method": "KHQR"}])
    assert r.status_code == 422 and r.json()["code"] == "KHQR_MISMATCH"
    r = await sell(client, [line(para, "strip", 1)], [{"method": "PAYWAY", "currency": "USD", "amount": "0.90"}])
    assert r.status_code == 422  # PAYWAY needs its checkout


async def test_cancel_closes_the_checkout(client, pw) -> None:  # noqa: ANN001, F811
    c = await new_checkout(client)
    tran = c["payment"]["tran_id"]
    pw.txns[tran] = {"amount": Decimal("0.90"), "currency": "USD", "status": 2, "paid": None, "refunded": Decimal("0")}
    r = await client.post(f"{PREFIX}/payments/khqr/{c['payment']['id']}/cancel", headers=CASHIER)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert pw.txns[tran]["status"] == 7 and "close-transaction" in pw.calls


async def test_a_wrong_amount_is_flagged_and_refunded_like_khqr(client, pw) -> None:  # noqa: ANN001, F811
    c = await new_checkout(client, "0.90")
    tran = c["payment"]["tran_id"]
    pw.txns[tran] = {"amount": Decimal("0.90"), "currency": "USD", "status": 2, "paid": None, "refunded": Decimal("0")}
    pw.pay(tran, "0.50")
    await callback(client, tran)
    seen = await qr_status(client, c["payment"])
    assert seen["status"] == "review" and "Paid 0.50 USD" in seen["review_reason"]
    [due] = await refunds(client, "due")
    assert due["source"] == "review" and due["payment"]["kind"] == "checkout"
    r = await do_refund(client, due["id"])
    assert r.status_code == 200 and r.json()["method"] == "payway" and pw.txns[tran]["refunded"] == Decimal("0.5")
    assert [p for t, p in await outbox() if t == "khqr.refunded"]


async def test_the_fake_provider_has_no_form_but_the_owner_can_mark_it_paid(client, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(get_settings(), "khqr_provider", "fake")
    r = await client.post(f"{PREFIX}/payments/payway/checkout", json={"branch_id": str(PP1), "amount": "0.90"},
                          headers={**OWNER, **idem()})  # fmt: skip
    assert r.status_code == 201 and r.json()["form"] is None and r.json()["payment"]["provider"] == "fake"
    pay = await client.post(f"{PREFIX}/payments/khqr/{r.json()['payment']['id']}/fake-pay", headers=OWNER)
    assert pay.status_code == 204


@pytest.mark.skipif(os.environ.get("PAYWAY_SANDBOX_TEST") != "1", reason="opt-in: PAYWAY_SANDBOX_TEST=1 + PayWay settings")
async def test_sandbox_accepts_the_signed_purchase_form() -> None:
    """The real sandbox: our signed multipart form opens PayWay's checkout page (a wrong hash answers an error)."""
    from sales_service.config import Settings

    s = Settings()
    payway.check_settings(s)
    api = payway.PayWay(s)
    tran = f"T{datetime.now(UTC):%y%m%d%H%M%S}{os.getpid() % 10000:04d}"
    fields = api.checkout_form(tran, Decimal("0.01"), "USD", "", 3, "https://example.com/cancel", "https://example.com/done")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
        r = await http.post(api.purchase_url, files={k: (None, v) for k, v in fields.items()})  # multipart/form-data
        bad = await http.post(api.purchase_url, files={k: (None, ("x" + v[1:]) if k == "hash" else v)
                                                       for k, v in fields.items()})  # fmt: skip
    # signed right: a 302 to the hosted checkout page; one changed character: 403 "Wrong hash" (code 1)
    assert r.history and r.history[0].status_code == 302 and r.status_code == 200
    assert "<title>PayWay - Checkout</title>" in r.text
    assert bad.status_code == 403 and payway.status_code(bad.json()) == "1"
