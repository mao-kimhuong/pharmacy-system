"""ABA PayWay (https://developer.payway.com.kh): KHQR by the QR API, its status by check-transaction-2,
close-transaction for a QR given up, and the refund API.

- Every request is JSON with a `hash` = base64(HMAC-SHA512(fields concatenated in the documented order,
  PAYWAY_API_KEY)). Times are UTC YYYYMMDDHHmmss (`req_time`; the refund API calls it `request_time`).
- Refund: `merchant_auth` = the JSON {mc_id, tran_id, refund_amount} encrypted with ABA's RSA public key,
  PKCS#1 v1.5, in chunks of (key bytes − 11) = 117 for a 1024-bit key, concatenated, base64.
- `status.code` comes as "00", "0", 6 or "PTL37": compared as text with "0" and "00" both meaning success. The
  same number means different things per API (check: 6 = not found; QR: 6 = domain not whitelisted).
- PAYWAY_BASE_URL may be a bare host or a full endpoint someone copied: only what comes before "/api/" is used.
- Nothing secret is ever logged or put in an error: not the API key, not merchant_auth, not the hash.
"""

import base64
import hashlib
import hmac
import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from pharmacy_shared.errors import AppError, ErrorCode

log = logging.getLogger(__name__)

QR_PATH = "/api/payment-gateway/v1/payments/generate-qr"
PURCHASE_PATH = "/api/payment-gateway/v1/payments/purchase"  # the browser posts the signed form here
CHECK_PATH = "/api/payment-gateway/v1/payments/check-transaction-2"
CLOSE_PATH = "/api/payment-gateway/v1/payments/close-transaction"
REFUND_PATH = "/api/merchant-portal/merchant-access/online-transaction/refund"

# check-transaction-2 data.payment_status_code
PAID, PENDING, DECLINED, REFUNDED, CANCELLED = 0, 2, 3, 4, 7
CHECK_NOT_FOUND = "6"

# Refund API codes → ours (status, message). Anything else: PAYWAY_REJECTED with PayWay's code.
REFUND_ERRORS: dict[str, tuple[ErrorCode, int, str]] = {
    "PTL02": (ErrorCode.PAYWAY_AUTH_FAILED, 502, "PayWay refused the request signature: check PAYWAY_API_KEY"),
    "PTL37": (ErrorCode.KHQR_REFUND_TOO_MUCH, 422, "The refund is more than what was paid"),
    "PTL168": (ErrorCode.KHQR_REFUND_BUSY, 409, "PayWay is still working on another refund of this payment: try again in a few seconds"),  # noqa: E501
    "PTL181": (ErrorCode.KHQR_REFUND_NO_BALANCE, 409, "The merchant account has not enough balance for this refund"),
}

REQUIRED = ("PAYWAY_BASE_URL", "PAYWAY_MERCHANT_ID", "PAYWAY_API_KEY", "PAYWAY_RSA_PUBLIC_KEY_FILE")


# ---------------------------------------------------------------- settings and keys


def api_root(base_url: str) -> str:
    """scheme://host[:port][/prefix] without a trailing slash; a copied endpoint path is dropped from "/api/"."""
    parts = urlsplit(base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("not an http(s) URL")
    path = parts.path
    if "/api/" in path:
        path = path[: path.index("/api/")]
    path = path.removesuffix("/api").rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _pem(text: str, kind: str) -> bytes:
    """A PEM with or without its BEGIN/END lines (ABA's portal shows the bare base64)."""
    body = text.strip()
    if "-----BEGIN" in body:
        return body.encode()
    b64 = "".join(body.split())
    lines = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
    return f"-----BEGIN {kind}-----\n{lines}\n-----END {kind}-----\n".encode()


def load_public_key(path: str) -> Any:  # noqa: ANN401 – cryptography's RSAPublicKey
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

    key = serialization.load_pem_public_key(_pem(Path(path).read_text(encoding="utf-8"), "PUBLIC KEY"))
    if not isinstance(key, RSAPublicKey):
        raise ValueError("not an RSA public key")
    return key


def check_settings(settings: Any) -> None:  # noqa: ANN401 – sales Settings (no import cycle)
    """Start-up (KHQR_PROVIDER=payway): every setting there, the base URL usable, ABA's public key readable.
    The private key file is only checked for being readable when it is set (no API used here needs it)."""
    values = {"PAYWAY_BASE_URL": settings.payway_base_url, "PAYWAY_MERCHANT_ID": settings.payway_merchant_id,
              "PAYWAY_API_KEY": settings.payway_api_key.get_secret_value(),
              "PAYWAY_RSA_PUBLIC_KEY_FILE": settings.payway_rsa_public_key_file}  # fmt: skip
    missing = [name for name in REQUIRED if not str(values[name]).strip()]
    if missing:
        raise RuntimeError(f"KHQR_PROVIDER=payway needs {', '.join(missing)}")
    try:
        api_root(settings.payway_base_url)
    except ValueError:
        raise RuntimeError("PAYWAY_BASE_URL is not an http(s) URL") from None
    try:
        load_public_key(settings.payway_rsa_public_key_file)
    except OSError:
        raise RuntimeError("PAYWAY_RSA_PUBLIC_KEY_FILE cannot be read") from None
    except ValueError:
        raise RuntimeError("PAYWAY_RSA_PUBLIC_KEY_FILE is not an RSA public key (PEM); in Docker set "
                           "PAYWAY_RSA_PUBLIC_KEY_SOURCE in .env to the key file") from None
    private = settings.payway_rsa_private_key_file
    if private and not Path(private).is_file():
        raise RuntimeError("PAYWAY_RSA_PRIVATE_KEY_FILE cannot be read")
    if settings.payway_callback_url:
        try:
            api_root(settings.payway_callback_url)
        except ValueError:
            raise RuntimeError("PAYWAY_CALLBACK_URL is not an http(s) URL") from None


# ---------------------------------------------------------------- signing


def req_time(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%d%H%M%S")


def sign(api_key: str, *parts: str) -> str:
    digest = hmac.new(api_key.encode(), "".join(parts).encode(), hashlib.sha512).digest()
    return base64.b64encode(digest).decode()


def amount_text(amount: Decimal) -> str:
    """The amount as PayWay hashes it and as the JSON number reads: 1.5 (not 1.50), 4000 (not 4000.00)."""
    text = format(amount.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def amount_json(amount: Decimal) -> int | float:
    text = amount_text(amount)
    return float(text) if "." in text else int(text)


def merchant_auth(public_key: Any, merchant_id: str, tran_id: str, amount: Decimal) -> str:  # noqa: ANN401
    from cryptography.hazmat.primitives.asymmetric import padding

    plain = json.dumps({"mc_id": merchant_id, "tran_id": tran_id, "refund_amount": amount_json(amount)},
                       separators=(",", ":")).encode()  # fmt: skip
    size = public_key.key_size // 8 - 11  # PKCS#1 v1.5 overhead; 117 for ABA's 1024-bit key
    chunks = [public_key.encrypt(plain[i : i + size], padding.PKCS1v15()) for i in range(0, len(plain), size)]
    return base64.b64encode(b"".join(chunks)).decode()


def status_code(body: dict[str, Any]) -> str:
    """status.code as text; "0" and "00" are both success. `status` may sit at the top or inside `data`."""
    status = body.get("status")
    if not isinstance(status, dict):
        status = (body.get("data") or {}).get("status") if isinstance(body.get("data"), dict) else None
    code = str((status or {}).get("code", "")).strip()
    return "00" if code in ("0", "00") else code


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# ---------------------------------------------------------------- the client


@dataclass
class Check:
    code: str  # "00" or PayWay's error code ("6" = not found)
    payment_status_code: int | None = None
    payment_amount: Decimal | None = None
    payment_currency: str | None = None
    refund_amount: Decimal = Decimal("0")
    apv: str | None = None
    transaction_date: str | None = None


@dataclass
class Qr:
    qr_string: str
    deeplink: str | None


@dataclass
class Refund:
    total_refunded: Decimal
    currency: str | None
    transaction_status: str | None


def _dec(value: Any) -> Decimal | None:  # noqa: ANN401
    return None if value is None or value == "" else Decimal(str(value))


class PayWay:
    def __init__(self, settings: Any, transport: httpx.AsyncBaseTransport | None = None) -> None:  # noqa: ANN401
        self.settings, self.transport = settings, transport
        self.root = api_root(settings.payway_base_url)
        self.merchant_id = settings.payway_merchant_id
        self._key = settings.payway_api_key.get_secret_value()

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3), transport=self.transport) as client:
                r = await client.post(self.root + path, json=body, headers={"Accept": "application/json"})
            answer = r.json() if r.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("PayWay %s unreachable: %s", path, type(exc).__name__)
            raise AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, "ABA PayWay cannot be reached; try again",
                           status_code=503) from exc  # fmt: skip
        if r.status_code >= 500 or not isinstance(answer, dict):
            raise AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, f"ABA PayWay answered {r.status_code}", status_code=503)
        return answer

    def _rejected(self, api: str, code: str, answer: dict[str, Any]) -> AppError:
        message = str(((answer.get("status") or {}).get("message")) or "")[:120]
        log.warning("PayWay %s refused: code %s", api, code)
        return AppError(ErrorCode.PAYWAY_REJECTED, f"ABA PayWay refused the {api}: {message or code}", status_code=502,
                        details={"provider_code": code})  # fmt: skip

    async def generate_qr(self, tran_id: str, amount: Decimal, currency: str, lifetime_minutes: int,
                          items: list[dict[str, Any]] | None = None) -> Qr:  # fmt: skip
        """POST generate-qr (payment_option abapay_khqr). Optional fields we do not send hash as empty text."""
        f = {"req_time": req_time(), "merchant_id": self.merchant_id, "tran_id": tran_id,
             "amount": amount_text(amount), "items": b64(json.dumps(items, separators=(",", ":"))) if items else "",
             "first_name": "", "last_name": "", "email": "", "phone": "", "purchase_type": "purchase",
             "payment_option": "abapay_khqr",
             "callback_url": b64(self.settings.payway_callback_url) if self.settings.payway_callback_url else "",
             "return_deeplink": "", "currency": currency, "custom_fields": "", "return_params": "", "payout": "",
             "lifetime": str(max(3, lifetime_minutes)), "qr_image_template": self.settings.payway_qr_template}  # fmt: skip
        order = ("req_time", "merchant_id", "tran_id", "amount", "items", "first_name", "last_name", "email", "phone",
                 "purchase_type", "payment_option", "callback_url", "return_deeplink", "currency", "custom_fields",
                 "return_params", "payout", "lifetime", "qr_image_template")  # fmt: skip
        body: dict[str, Any] = {k: v for k, v in f.items() if v != ""}
        body["amount"], body["lifetime"] = amount_json(amount), int(f["lifetime"])
        body["hash"] = sign(self._key, *(f[k] for k in order))
        answer = await self._post(QR_PATH, body)
        code = status_code(answer)
        if code != "00" or not answer.get("qrString"):
            raise self._rejected("QR", code or "?", answer)
        return Qr(answer["qrString"], answer.get("abapay_deeplink"))

    def checkout_form(self, tran_id: str, amount: Decimal, currency: str, payment_option: str, lifetime: int,
                      cancel_url: str, continue_success_url: str) -> dict[str, str]:  # fmt: skip
        return purchase_form(self._key, self.merchant_id, tran_id, amount, currency, payment_option=payment_option,
                             return_url=self.settings.payway_callback_url, cancel_url=cancel_url,
                             continue_success_url=continue_success_url, lifetime=lifetime)  # fmt: skip

    @property
    def purchase_url(self) -> str:
        return self.root + PURCHASE_PATH

    async def check(self, tran_id: str) -> Check:
        t = req_time()
        answer = await self._post(CHECK_PATH, {"req_time": t, "merchant_id": self.merchant_id, "tran_id": tran_id,
                                               "hash": sign(self._key, t, self.merchant_id, tran_id)})  # fmt: skip
        code = status_code(answer)
        if code != "00":
            return Check(code)
        d = answer.get("data") or {}
        return Check(code, int(d["payment_status_code"]) if d.get("payment_status_code") is not None else None,
                     _dec(d.get("payment_amount")), (d.get("payment_currency") or "").upper() or None,
                     _dec(d.get("refund_amount")) or Decimal("0"), d.get("apv"), d.get("transaction_date"))  # fmt: skip

    async def close(self, tran_id: str) -> str:
        """Close a QR given up (no payment is taken after). Returns PayWay's code; "5" = not found."""
        t = req_time()
        answer = await self._post(CLOSE_PATH, {"req_time": t, "merchant_id": self.merchant_id, "tran_id": tran_id,
                                               "hash": sign(self._key, t, self.merchant_id, tran_id)})  # fmt: skip
        return status_code(answer)

    async def refund(self, tran_id: str, amount: Decimal) -> Refund:
        key = load_public_key(self.settings.payway_rsa_public_key_file)
        t = req_time()
        auth = merchant_auth(key, self.merchant_id, tran_id, amount)
        answer = await self._post(REFUND_PATH, {"request_time": t, "merchant_id": self.merchant_id,
                                                "merchant_auth": auth, "hash": sign(self._key, t, self.merchant_id, auth)})  # fmt: skip
        code = status_code(answer)
        if code != "00":
            if code in REFUND_ERRORS:
                err, status, message = REFUND_ERRORS[code]
                log.warning("PayWay refund refused: code %s", code)
                raise AppError(err, message, status_code=status, details={"provider_code": code})
            raise self._rejected("refund", code or "?", answer)
        return Refund(_dec(answer.get("total_refunded")) or amount, answer.get("currency"),
                      answer.get("transaction_status"))  # fmt: skip


# Purchase (docs/payway/purchase.md): the hash takes these fields in exactly this order (empty = not sent)
PURCHASE_HASH_ORDER = ("req_time", "merchant_id", "tran_id", "amount", "items", "shipping", "firstname", "lastname",
                       "email", "phone", "type", "payment_option", "return_url", "cancel_url", "continue_success_url",
                       "return_deeplink", "currency", "custom_fields", "return_params", "payout", "lifetime",
                       "additional_params", "google_pay_token", "skip_success_page")  # fmt: skip
CHECKOUT_OPTIONS = ("cards", "abapay_khqr", "alipay", "wechat", "google_pay")


def purchase_form(api_key: str, merchant_id: str, tran_id: str, amount: Decimal, currency: str, *,
                  return_url: str = "", cancel_url: str = "", continue_success_url: str = "", payment_option: str = "",
                  lifetime: int = 0, items: list[dict[str, Any]] | None = None,
                  at: datetime | None = None) -> dict[str, str]:  # fmt: skip
    """The multipart/form-data fields the browser posts to PURCHASE_PATH (PayWay's hosted checkout opens).
    return_url is where PayWay pushes the result (our callback, base64 as the docs say); cancel_url and
    continue_success_url are pages of the web app. view_type and payment_gate are sent, not hashed (per the docs)."""
    f = {k: "" for k in PURCHASE_HASH_ORDER}
    f.update({"req_time": req_time(at), "merchant_id": merchant_id, "tran_id": tran_id, "amount": amount_text(amount),
              "items": b64(json.dumps(items, separators=(",", ":"))) if items else "", "type": "purchase",
              "payment_option": payment_option, "return_url": b64(return_url) if return_url else "",
              "cancel_url": cancel_url, "continue_success_url": continue_success_url, "currency": currency,
              "lifetime": str(lifetime) if lifetime else "", "skip_success_page": "1" if continue_success_url else ""})  # fmt: skip
    fields = {k: v for k, v in f.items() if v != ""}
    fields["hash"] = sign(api_key, *(f[k] for k in PURCHASE_HASH_ORDER))
    fields["view_type"] = "hosted_view"
    fields["payment_gate"] = "0"  # the Checkout service, also when the profile has the QR API
    return fields


def lifetime_minutes(seconds: int) -> int:
    return max(3, math.ceil(seconds / 60))
