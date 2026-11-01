#!/usr/bin/env python3
"""End-to-end smoke test through Traefik (needs `make up` and `make owner` first).

    make smoke

S0 checks: health, protected routes, faked headers, login (+ 2FA), logout.
S1 checks (optional, you are asked): create a test branch, wait for the auth
service to learn about it over RabbitMQ, create a cashier there, check the
cashier's permissions, deactivate the cashier (logged out at once), User Log.
The test branch and cashier are deactivated at the end.
S1b checks (optional, you are asked): import docs/samples/products-sample-broken.xlsx
(its bad row is shown, nothing saved), then products-sample.xlsx (20 products,
creating its categories and brands; the products stay), search by barcode,
Khmer and English name, print labels as a PDF, a cashier gets 403 on edit and
import, and the User Log shows the import.

S2 checks (optional, needs the S1b sample products): in a new test branch, a
supplier and a PO for PARA500, AMOX500 and ORS, the PO PDF, receiving 2 lots per
line (a past expiry refused, a short expiry flagged, the same Idempotency-Key not
doubling stock), stock shown FEFO, paying the supplier to 0, a cashier seeing stock
without cost fields, the User Log. The test branch, cashier and supplier are deactivated.

S3 checks (optional, needs the S1b sample products): in a new test branch, stock-in,
the KHR rate, a cashier selling 2 items for mixed USD/KHR cash (change, FEFO split,
80mm receipt), the same Idempotency-Key not selling twice, two tills selling the
last unit at once, Rx-only / controlled refused without an Rx, a credit sale over the limit
refused (nothing left reserved), a credit sale + customer payment, a cashier's 403
on cancel, cancel back to the same batches, a partial return, /internal not
reachable through Traefik, the User Log.

S4 checks (optional, needs the S1b sample products): in a new test branch, a
pharmacist creates a patient (allergic to amoxicillin) and a doctor, writes an Rx
for AMOX500, uploads a test Rx image and opens it again through the service (safe
headers; a cashier gets 403), a cashier cannot dispense, the allergy warning
blocks the sale until the pharmacist overrides it with a reason, part of the Rx is
sold and the rest is shown as remaining, selling more than the Rx allows is
refused, the dispensing label and the Rx summary print, the User Log.

S5 checks (optional, needs the S1b sample products): in a new test branch, two
pharmacists set their PINs; DIAZ5 (controlled) is stocked in and reaches the
register; a controlled sale on an Rx needs the patient's ID and the PIN (refused
without it); destroying one tablet with a pharmacist as witness is refused, with a branch
manager's PIN (2FA on) it works; the register shows
receive / dispense / destroy with the right balance and its hash chain verifies;
the register PDF prints; a controlled stock take is counted by both pharmacists
(one tablet short), approved with a PIN and posted to stock and the register;
the User Log.

S6 checks (optional, needs the S1b sample products): two new test branches A and B;
PARA500 stocked at A; B requests 40, A approves, picks FEFO and dispatches (stock in
transit), B's cashier receives 3 short, the difference is written off and the
transfer closes (stock and in transit add up), the transfer note prints with its
QR code; a purchase request at A becomes a PO group with a PO for A (printout for
the supplier); B's re-order list is run with a min/max for PARA500 and printed.

S7 checks (optional, needs the S1b sample products): a test branch with stock; a
cart suspended by the cashier is resumed by the owner (re-priced, no changes); a
buy-2-get-1 promotion on ORS (this branch only) prices 3 sachets as 2 and the
sale stores it; a hamper (10 PARA500 + 5 CETI10) is sold from its components'
batches; a quote becomes an order with a deposit and a reservation, is partly
invoiced with the deposit, printed, and the rest cancelled; a 5 % commission rule,
a sale, the report and the cashier's own drill-down (not someone else's).

S8 checks (optional, needs the S1b sample products): a test branch with two sales
(USD and KHR) and a return; the dashboard shows them (profit for the owner, not
the cashier); Sale Detail totals equal the invoices; CSV, XLSX and PDF exports;
the cashier gets 403 on Sale Margin By Item; /internal/v1/outbox is not routed;
Telegram: the test message (503 without a bot token), the daily summary queued
once when run twice, the User Log.

S8b checks (optional, needs the S1b sample products and KHQR_PROVIDER=fake): a test
branch receives PARA500 from a new supplier; the cart preview says can_post for it,
RX_REQUIRED for AMOX500 without an Rx and PHARMACIST_REQUIRED for a cashier's Rx
line; a KHQR is created, paid (fake Bakong) and pays a sale once; a supplier
return lowers what we owe and prints; a recall of the lot stops its sale (lifted
afterwards); a customer statement prints in Khmer and English; the owner logs in
with a new backup code and that session is revoked at once.

Without prompts: SMOKE_PHONE, SMOKE_PASSWORD, SMOKE_S1=y ... SMOKE_S5=y, SMOKE_S6=y, SMOKE_S7=y, SMOKE_S8=y, SMOKE_S8B=y.

Uses only the Python standard library.
"""

import base64
import getpass
import hashlib
import hmac
import json
import os
import random
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

BASE = os.environ.get("BASE_URL", "http://localhost").rstrip("/")
SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "samples"
PREFIXES = [
    "auth", "branch", "catalog", "inventory", "stockcount", "prescription", "controlled",
    "sales", "customers", "purchasing", "reports", "notifications", "documents", "ai",
]  # fmt: skip
results: list[tuple[bool, str]] = []


def call(
    method: str, path: str, body: dict | None = None, token: str | None = None, headers: dict | None = None
):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return err.code, {"raw": raw.decode(errors="replace")}
    except urllib.error.URLError as err:
        print(f"Cannot reach {BASE}: {err.reason}. Is the stack running (make up)?")
        sys.exit(2)


def call_raw(method: str, path: str, data: bytes | None, token: str, headers: dict | None = None):
    """Like call(), for uploads and binary answers: (status, body bytes, content type)."""
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=dict(headers or {}))
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as err:
        return err.code, err.read(), err.headers.get("Content-Type", "")


def upload(path: str, file: Path, token: str) -> tuple[int, dict]:
    boundary = uuid.uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
            "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
        ).encode()
        + file.read_bytes()
        + f"\r\n--{boundary}--\r\n".encode()
    )
    status, raw, _ = call_raw(
        "POST", path, body, token, {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, {"raw": raw[:200].decode(errors="replace")}


def check(ok: bool, label: str) -> bool:
    results.append((bool(ok), label))
    print(("  PASS  " if ok else "  FAIL  ") + label)
    return bool(ok)


OWNER_LOGIN: dict[str, str] = {}  # kept for the S8b backup-code check


def owner_login() -> dict | None:
    phone = os.environ.get("SMOKE_PHONE") or input("Owner phone: ")
    password = os.environ.get("SMOKE_PASSWORD") or getpass.getpass("Owner password: ")
    OWNER_LOGIN.update(phone=phone, password=password)
    status, data = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})
    if not check(status == 200, f"owner login -> 200 (got {status} {data.get('code', '')})"):
        return None

    if data.get("mfa_required"):
        code = input("6-digit code from your authenticator app: ").strip()
        status, data = call("POST", "/api/auth/v1/login/2fa", {"mfa_token": data["mfa_token"], "code": code})
        if not check(status == 200, f"2FA code accepted (got {status} {data.get('code', '')})"):
            return None

    if data.get("mfa_setup_required"):
        status, _ = call("GET", "/api/sales/v1/whoami", token=data["access_token"])
        check(status == 403, f"before 2FA set-up, other services are blocked -> 403 (got {status})")
        print("\n  Two-factor login is required for the owner. Set it up now:")
        status, setup = call("POST", "/api/auth/v1/2fa/setup", token=data["access_token"])
        if not check(status == 200, f"2FA set-up started (got {status})"):
            return None
        print("  In Google Authenticator / Microsoft Authenticator / 2FAS, add an account")
        print(f"  with this key:  {setup['secret']}")
        print("  (or open the QR code from the API docs: POST /api/auth/v1/2fa/setup)\n")
        code = input("  6-digit code shown in the app: ").strip()
        status, data = call("POST", "/api/auth/v1/2fa/enable", {"code": code}, token=data["access_token"])
        if not check(status == 200, f"2FA turned on (got {status} {data.get('code', '')})"):
            return None
    return data


def s0_checks() -> dict | None:
    healthy = [p for p in PREFIXES if call("GET", f"/api/{p}/v1/health")[0] == 200]
    check(len(healthy) == len(PREFIXES), f"health is public on all services ({len(healthy)}/{len(PREFIXES)})")
    status, _ = call("GET", "/api/sales/v1/whoami")
    check(status == 401, f"protected endpoint without token -> 401 (got {status})")
    fake = {"X-User-Id": "11111111-1111-1111-1111-111111111111", "X-Role": "owner", "X-Permissions": "*"}
    status, _ = call("GET", "/api/sales/v1/whoami", headers=fake)
    check(status == 401, f"faked identity headers are ignored -> 401 (got {status})")

    tokens = owner_login()
    if tokens is None:
        return None
    token = tokens["access_token"]
    status, who = call("GET", "/api/sales/v1/whoami", token=token)
    check(
        status == 200 and who.get("permissions") == ["*"],
        f"owner reaches other services with all permissions ({status})",
    )
    status, who = call(
        "GET",
        "/api/sales/v1/whoami",
        token=token,
        headers={**fake, "X-User-Id": "2" * 8 + "-2222-2222-2222-" + "2" * 12},
    )
    check(
        status == 200 and who.get("user_id") == tokens["user"]["id"],
        "with a token, faked headers are replaced",
    )
    status, me = call("GET", "/api/auth/v1/me", token=token)
    check(
        status == 200 and len(me.get("menu", [])) > 10,
        f"/me returns permissions and menu ({len(me.get('menu', []))} items)",
    )
    return tokens


def make_test_cashier(token: str) -> tuple[str, dict, str, str] | None:
    """A test branch and a cashier in it: (branch_id, cashier, phone, password)."""
    code = f"T{random.randint(1000, 9999)}"
    status, branch = call(
        "POST",
        "/api/branch/v1/branches",
        {"code": code, "name_km": "សាខាតេស្ត", "name_en": f"Smoke test {code}"},
        token=token,
    )
    if not check(status == 201, f"create test branch {code} -> 201 (got {status} {branch.get('code', '')})"):
        return None
    bid = branch["id"]

    phone = f"09{random.randint(1000000, 9999999)}"
    password = f"smoke-{random.randint(100000, 999999)}"
    body = {
        "name": "Smoke cashier",
        "phone": phone,
        "password": password,
        "role": "cashier",
        "branch_ids": [bid],
    }
    status, cashier = 0, {}
    for _ in range(20):  # the branch reaches the auth service through RabbitMQ
        status, cashier = call("POST", "/api/auth/v1/users", body, token=token)
        if cashier.get("code") != "UNKNOWN_BRANCH":
            break
        time.sleep(0.5)
    if not check(
        status == 201,
        f"auth learned the branch over RabbitMQ; cashier created -> 201 (got {status} {cashier.get('code', '')})",
    ):
        call("POST", f"/api/branch/v1/branches/{bid}/deactivate", {"reason": "smoke test"}, token=token)
        return None
    return bid, cashier, phone, password


def remove_test_cashier(token: str, bid: str, cashier: dict) -> None:
    call("POST", f"/api/auth/v1/users/{cashier['id']}/deactivate", {"reason": "smoke test"}, token=token)
    status, _ = call(
        "POST", f"/api/branch/v1/branches/{bid}/deactivate", {"reason": "smoke test"}, token=token
    )
    check(status == 200, "test cashier and branch deactivated")


def s1_checks(token: str) -> None:
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, phone, password = made

    status, ctok = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})
    check(status == 200, f"cashier logs in without 2FA -> 200 (got {status})")
    ctoken = ctok.get("access_token", "")
    status, who = call("GET", "/api/sales/v1/whoami", token=ctoken)
    check(status == 200 and "pos.sell" in who.get("permissions", []), "cashier has pos.sell")
    check("settings.users" not in who.get("permissions", []), "cashier does not have settings.users")
    status, _ = call("GET", "/api/auth/v1/users", token=ctoken)
    check(status == 403, f"cashier opening user management -> 403 (got {status})")
    status, _ = call("GET", "/api/branch/v1/branches", token=ctoken)
    check(status == 200, "cashier sees their branch")

    status, _ = call(
        "POST", f"/api/auth/v1/users/{cashier['id']}/deactivate", {"reason": "smoke test"}, token=token
    )
    check(status == 200, f"owner deactivates the cashier -> 200 (got {status})")
    status, _ = call("GET", "/api/sales/v1/whoami", token=ctoken)
    check(status == 401, f"deactivated cashier is logged out at once -> 401 (got {status})")

    status, log = call("GET", "/api/auth/v1/audit-logs?action=user.deactivated&size=5", token=token)
    check(status == 200 and log.get("total", 0) >= 1, "User Log shows the deactivation")
    found = False
    for _ in range(20):  # branch.created comes from the branch service as an event
        status, log = call(
            "GET", f"/api/auth/v1/audit-logs?action=branch.created&entity_id={bid}", token=token
        )
        if log.get("total"):
            found = True
            break
        time.sleep(0.5)
    check(found, "User Log shows the branch creation sent by the branch service")

    status, _ = call(
        "POST", f"/api/branch/v1/branches/{bid}/deactivate", {"reason": "smoke test"}, token=token
    )
    check(status == 200, "test branch deactivated")


def wait_for(fn, tries: int = 30, delay: float = 0.5):
    """Retry fn() until it returns something truthy (events travel over RabbitMQ)."""
    result = None
    for _ in range(tries):
        result = fn()
        if result:
            return result
        time.sleep(delay)
    return result


def s1b_checks(token: str) -> None:
    cat = "/api/catalog/v1"
    _, before = call("GET", f"{cat}/medicines?include_inactive=true&size=1", token=token)
    total_before = before.get("total", 0)

    # A file with one bad row: the row's error is shown and nothing is saved.
    status, imp = upload(f"{cat}/imports", SAMPLES / "products-sample-broken.xlsx", token)
    check(status == 201, f"upload broken sample -> 201 (got {status} {imp.get('code', '')})")
    if status == 201:
        _, d = call("GET", f"{cat}/imports/{imp['id']}?errors_only=true", token=token)
        bad = [(r["row_no"], r["sku"], e) for r in d.get("rows", []) for e in r["errors"]
               if e["code"] not in ("UNKNOWN_CATEGORY", "UNKNOWN_BRAND")]  # fmt: skip
        check(
            len(bad) == 1 and bad[0][1] == "AMOX500" and bad[0][2]["code"] == "DUPLICATE_BARCODE",
            f"broken file: exactly one bad row is reported ({[(r, s, e['message']) for r, s, e in bad]})",
        )
        status, body = call("POST", f"{cat}/imports/{imp['id']}/commit", {"create_missing": True}, token=token,
                            headers={"Idempotency-Key": str(uuid.uuid4())})  # fmt: skip
        check(status == 422 and body.get("code") == "IMPORT_HAS_ERRORS",
              f"commit of the broken file is refused -> 422 (got {status} {body.get('code', '')})")  # fmt: skip
        _, after = call("GET", f"{cat}/medicines?include_inactive=true&size=1", token=token)
        check(after.get("total") == total_before, "nothing was saved from the broken file")

    # The fixed file commits 20 products (creating its categories and brands).
    status, imp = upload(f"{cat}/imports", SAMPLES / "products-sample.xlsx", token)
    if not check(status == 201, f"upload products-sample.xlsx -> 201 (got {status} {imp.get('code', '')})"):
        return
    status, done = call("POST", f"{cat}/imports/{imp['id']}/commit", {"create_missing": True}, token=token,
                        headers={"Idempotency-Key": str(uuid.uuid4())})  # fmt: skip
    check(
        status == 200 and done.get("status") == "committed" and not done.get("skipped_skus"),
        f"sample committed -> 200 (got {status} {done.get('code', '')}; created {done.get('created_count')},"
        f" updated {done.get('updated_count')})",
    )
    _, after = call("GET", f"{cat}/medicines?include_inactive=true&size=1", token=token)
    check(after.get("total", 0) >= 20, f"catalog has the 20 sample products ({after.get('total')} in total)")

    # Search: barcode first, Khmer name, English name.
    _, found = call("GET", f"{cat}/medicines/search?q=PARA500", token=token)
    para = (found.get("items") or [{}])[0]
    box = next((p for p in para.get("pack_units", []) if p["name"] == "box"), None)
    if not check(
        para.get("sku") == "PARA500" and box is not None, "search by SKU finds PARA500 with its box"
    ):
        return
    _, found = call("GET", f"{cat}/medicines/search?q={box['barcode']}", token=token)
    first = (found.get("items") or [{}])[0]
    check(first.get("sku") == "PARA500" and first.get("matched_pack_unit_id") == box["id"],
          f"search by barcode {box['barcode']} -> PARA500 box first")  # fmt: skip
    khmer = urllib.parse.quote("អាម៉ុកស៊ីស៊ីលីន")
    _, found = call("GET", f"{cat}/medicines/search?q={khmer}", token=token)
    check("AMOX500" in [m["sku"] for m in found.get("items", [])], "search by Khmer name finds Amoxicillin")
    _, found = call("GET", f"{cat}/medicines/search?q=amoxicillin", token=token)
    check("AMOX500" in [m["sku"] for m in found.get("items", [])], "search by English name finds Amoxicillin")

    # Labels: the document service learns the products from medicine.* events.
    label_body = json.dumps({"type": "label", "layout": "shelf_50x30",
                             "items": [{"pack_unit_id": box["id"], "copies": 2}]}).encode()  # fmt: skip

    def render():
        status, pdf, ctype = call_raw("POST", "/api/documents/v1/render", label_body, token,
                                      {"Content-Type": "application/json"})  # fmt: skip
        return (status, pdf, ctype) if status == 200 else None

    rendered = wait_for(render, tries=40)
    if check(
        rendered is not None and rendered[2] == "application/pdf" and rendered[1].startswith(b"%PDF"),
        "labels print as a PDF (document service got the products over RabbitMQ)",
    ):
        out = Path(tempfile.gettempdir()) / "pharmacy-smoke-labels.pdf"
        out.write_bytes(rendered[1])
        print(f"        open {out} to check the Khmer text")

    # A cashier can view products but not edit, import or print labels.
    made = make_test_cashier(token)
    if made is not None:
        bid, cashier, phone, password = made
        _, ctok = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})
        ctoken = ctok.get("access_token", "")
        status, _ = call("GET", f"{cat}/medicines/search?q=PARA500", token=ctoken)
        check(status == 200, f"cashier can view products -> 200 (got {status})")
        status, _ = call("PATCH", f"{cat}/medicines/{para['id']}", {"reorder_level": 1}, token=ctoken)
        check(status == 403, f"cashier editing a product -> 403 (got {status})")
        status, _ = upload(f"{cat}/imports", SAMPLES / "products-sample.xlsx", ctoken)
        check(status == 403, f"cashier importing products -> 403 (got {status})")
        status, _, _ = call_raw("POST", "/api/documents/v1/render", label_body, ctoken,
                                {"Content-Type": "application/json"})  # fmt: skip
        check(status == 403, f"cashier printing labels -> 403 (got {status})")
        remove_test_cashier(token, bid, cashier)

    # User Log (the catalog's audit events reach the auth service over RabbitMQ).
    def logged():
        _, log = call(
            "GET", f"/api/auth/v1/audit-logs?action=import.committed&entity_id={imp['id']}", token=token
        )
        return log.get("total")

    check(bool(wait_for(logged)), "User Log shows the import")
    _, log = call("GET", f"/api/auth/v1/audit-logs?entity_type=medicine&entity_id={para['id']}", token=token)
    check(log.get("total", 0) >= 1, "User Log shows changes to PARA500")


def s2_checks(token: str) -> None:
    cat, pur, inv = "/api/catalog/v1", "/api/purchasing/v1", "/api/inventory/v1"
    products = {}
    for sku in ("PARA500", "AMOX500", "ORS"):
        _, found = call("GET", f"{cat}/medicines/search?q={sku}", token=token)
        m = next((x for x in found.get("items", []) if x["sku"] == sku), None)
        if m is None:
            check(False, f"sample product {sku} exists (run the S1b step first)")
            return
        products[sku] = (m, next(p for p in m["pack_units"] if p["name"] == "box"))
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, phone, password = made
    code = f"S2{random.randint(1000, 9999)}"
    status, supplier = call("POST", f"{pur}/suppliers", {"code": code, "name": f"Smoke supplier {code}",
                            "name_km": "អ្នកផ្គត់ផ្គង់", "payment_terms_days": 30}, token=token)  # fmt: skip
    check(status == 201, f"owner creates supplier {code} -> 201 (got {status} {supplier.get('code', '')})")
    if status != 201:
        return remove_test_cashier(token, bid, cashier)

    body = {"branch_id": bid, "supplier_id": supplier["id"], "note": "Smoke test PO", "lines": [
        {"medicine_id": m["id"], "pack_unit_id": box["id"], "qty": 2, "unit_cost": "4.25"}
        for m, box in products.values()]}  # fmt: skip

    def create_po():
        status, po = call("POST", f"{pur}/purchase-orders", body, token=token)
        return (status, po) if po.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

    status, po = wait_for(create_po, tries=30) or (0, {"code": "UNKNOWN_BRANCH / UNKNOWN_MEDICINE"})
    if not check(status == 201, f"PO for 3 sample products -> 201 (got {status} {po.get('code', '')}"
                 f"{'; run make resync' if po.get('code') else ''})"):  # fmt: skip
        return remove_test_cashier(token, bid, cashier)
    status, po = call("POST", f"{pur}/purchase-orders/{po['id']}/send", token=token)
    check(status == 200 and po.get("status") == "sent", f"PO {po.get('number')} sent")
    pdf_body = json.dumps({"type": "purchase_order", "purchase_order_id": po["id"]}).encode()

    def po_pdf():
        status, pdf, ctype = call_raw("POST", "/api/documents/v1/render", pdf_body, token,
                                      {"Content-Type": "application/json"})  # fmt: skip
        return (pdf, ctype) if status == 200 else None

    got = wait_for(po_pdf, tries=10)
    if check(got is not None and got[0].startswith(b"%PDF"), "PO PDF printed"):
        out = Path(tempfile.gettempdir()) / "pharmacy-smoke-po.pdf"
        out.write_bytes(got[0])
        print(f"        open {out}")

    today = date.today()
    soon, later, much_later = (
        today + timedelta(days=60),
        today + timedelta(days=500),
        today + timedelta(days=700),
    )
    first = po["lines"][0]
    status, err = call("POST", f"{pur}/purchase-orders/{po['id']}/receive", {"lines": [
        {"po_line_id": first["id"], "lot_no": "OLD", "expiry_date": (today - timedelta(days=1)).isoformat(), "qty": 1}]},
        token=token, headers={"Idempotency-Key": str(uuid.uuid4())})  # fmt: skip
    check(
        status == 409 and err.get("code") == "BATCH_EXPIRED",
        f"past expiry refused -> 409 BATCH_EXPIRED (got {status})",
    )

    lines = []
    for i, line in enumerate(po["lines"]):  # two lots per line; the first item's earlier lot is short-dated
        lines.append(
            {"po_line_id": line["id"], "lot_no": f"L{i}B", "expiry_date": much_later.isoformat(), "qty": 1}
        )
        lines.append({"po_line_id": line["id"], "lot_no": f"L{i}A",
                      "expiry_date": (soon if i == 0 else later).isoformat(), "qty": 1})  # fmt: skip
    key = {"Idempotency-Key": str(uuid.uuid4())}
    status, receipt = call("POST", f"{pur}/purchase-orders/{po['id']}/receive", {"lines": lines,
                           "supplier_invoice_no": "SMOKE-1"}, token=token, headers=key)  # fmt: skip
    check(status == 201, f"received 2 lots per line -> 201 (got {status} {receipt.get('code', '')})")
    flagged = [x["lot_no"] for x in receipt.get("lines", []) if x["short_expiry"]]
    check(flagged == ["L0A"], f"short expiry flagged ({flagged})")
    status, again = call("POST", f"{pur}/purchase-orders/{po['id']}/receive", {"lines": lines,
                         "supplier_invoice_no": "SMOKE-1"}, token=token, headers=key)  # fmt: skip
    check(
        status == 201 and again.get("number") == receipt.get("number"),
        "same Idempotency-Key replays the receipt",
    )

    expected = {m["sku"]: 2 * box["qty_in_base"] for m, box in products.values()}

    def stock_arrived():
        _, page = call("GET", f"{inv}/stock?branch_id={bid}", token=token)
        items = {i["sku"]: i for i in page.get("items", [])}
        return items if {k: items.get(k, {}).get("qty_on_hand") for k in expected} == expected else None

    items = wait_for(stock_arrived, tries=40)
    check(items is not None, f"stock arrived in the test branch, once ({expected})")
    if items:
        lots = [b["lot_no"] for b in items["PARA500"]["batches"]]
        check(lots == ["L0A", "L0B"], f"batches shown FEFO, earliest expiry first ({lots})")

    total = receipt.get("total", "0")
    status, payment = call("POST", f"{pur}/supplier-payments", {"supplier_id": supplier["id"], "branch_id": bid,
                           "method": "ABA", "amount": total}, token=token,
                           headers={"Idempotency-Key": str(uuid.uuid4())})  # fmt: skip
    check(status == 201, f"supplier paid {total} USD -> 201 (got {status} {payment.get('code', '')})")
    _, bal = call("GET", f"{pur}/suppliers/{supplier['id']}/balance", token=token)
    check(bal.get("owed") == "0.00", f"supplier balance is 0 ({bal.get('owed')})")

    _, ctok = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})
    status, raw, _ = call_raw("GET", f"{inv}/stock?branch_id={bid}", None, ctok.get("access_token", ""))
    text = raw.decode()
    check(status == 200 and "PARA500" in text and "cost_per_base" not in text and "stock_value" not in text,
          f"cashier sees stock without cost fields ({status})")  # fmt: skip

    for action, entity in (("purchase_order.created", po["id"]), ("goods.received", receipt.get("id")),
                           ("supplier_payment.created", payment.get("id"))):  # fmt: skip

        def logged(action=action, entity=entity):
            _, log = call("GET", f"/api/auth/v1/audit-logs?action={action}&entity_id={entity}", token=token)
            return log.get("total")

        check(bool(wait_for(logged)), f"User Log shows {action}")

    call("POST", f"{pur}/suppliers/{supplier['id']}/deactivate", {"reason": "smoke test"}, token=token)
    remove_test_cashier(token, bid, cashier)


def s3_checks(token: str) -> None:
    cat, inv, sales, cust = "/api/catalog/v1", "/api/inventory/v1", "/api/sales/v1", "/api/customers/v1"
    products = {}
    for sku in ("PARA500", "CETI10", "ORS", "AMOX500", "DIAZ5"):
        _, found = call("GET", f"{cat}/medicines/search?q={sku}", token=token)
        m = next((x for x in found.get("items", []) if x["sku"] == sku), None)
        if m is None:
            check(False, f"sample product {sku} exists (run the S1b step first)")
            return
        products[sku] = (m, {p["name"]: p for p in m["pack_units"]})
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, phone, password = made
    today = date.today()

    def key() -> dict:
        return {"Idempotency-Key": str(uuid.uuid4())}

    def stock_in_line(sku: str, pack: str, lot: str, days: int, qty: int) -> dict:
        m, packs = products[sku]
        return {"medicine_id": m["id"], "pack_unit_id": packs[pack]["id"], "lot_no": lot,
                "expiry_date": (today + timedelta(days=days)).isoformat(), "qty": qty, "unit_cost": "0.10"}  # fmt: skip

    body = {"branch_id": bid, "reason": "Smoke test S3", "lines": [
        stock_in_line("PARA500", "strip", "S3EARLY", 300, 1), stock_in_line("PARA500", "box", "S3LATE", 600, 1),
        stock_in_line("CETI10", "box", "S3C", 500, 2), stock_in_line("ORS", "sachet", "S3LAST", 500, 1)]}  # fmt: skip

    def stock_in():
        status, out = call("POST", f"{inv}/stock-in", body, token=token, headers=key())
        return (status, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

    status, out = wait_for(stock_in, tries=30) or (0, {"code": "UNKNOWN_BRANCH"})
    if not check(status == 201, f"stock-in for the test branch -> 201 (got {status} {out.get('code', '')}"
                 f"{'; run make resync' if out.get('code') else ''})"):  # fmt: skip
        return remove_test_cashier(token, bid, cashier)
    status, _ = call("PUT", f"{sales}/exchange-rates/{bid}", {"khr_per_usd": 4100}, token=token)
    check(status == 200, f"owner sets the KHR rate 4,100 -> 200 (got {status})")

    _, ctok = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})
    ctoken = ctok.get("access_token", "")

    def line(sku: str, pack: str, qty: int) -> dict:
        m, packs = products[sku]
        return {"medicine_id": m["id"], "pack_unit_id": packs[pack]["id"], "qty": qty}

    def sell(lines, payments, tok=None, headers=None, **extra):
        return call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": lines, "payments": payments, **extra},
                    token=tok or ctoken, headers=headers or key())  # fmt: skip

    strip = products["PARA500"][1]["strip"]["qty_in_base"]  # tablets per strip (12 in the sample)
    box = products["PARA500"][1]["box"]["qty_in_base"]
    para_strip = Decimal(products["PARA500"][1]["strip"]["sell_price"])
    ceti_strip = Decimal(products["CETI10"][1]["strip"]["sell_price"])
    # 1. mixed USD / KHR cash, 2 items; PARA500 2 strips = 1 strip from S3EARLY + 1 from S3LATE
    sale_key = key()
    payments = [{"method": "cash", "currency": "USD", "amount": "2.00"},
                {"method": "cash", "currency": "KHR", "amount": "10000"}]  # fmt: skip

    def first_sale():
        status, out = sell(
            [line("PARA500", "strip", 2), line("CETI10", "strip", 1)], payments, headers=sale_key
        )
        return (status, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

    status, sale = wait_for(first_sale, tries=30) or (0, {"code": "UNKNOWN_BRANCH"})
    if not check(status == 201, f"cashier sells 2 items for USD + KHR -> 201 (got {status} {sale.get('code', '')}"
                 f" {sale.get('message', '')})"):  # fmt: skip
        return remove_test_cashier(token, bid, cashier)
    total, paid = Decimal(sale["total"]), Decimal(sale["paid"])
    change = Decimal(sale["change_usd"])
    given = Decimal(sale["change_given_usd"]) + Decimal(sale["change_given_khr"]) / 4100
    check(paid == Decimal("2.00") + (Decimal(10000) / 4100).quantize(Decimal("0.01")) and change == paid - total
          and sale["change_given_khr"] % 100 == 0 and abs(given - change) < Decimal("0.0125"),
          f"change is right: total {total}, paid {paid}, change {sale['change_given_usd']} USD + "
          f"{sale['change_given_khr']} riel")  # fmt: skip
    lots = [(b["lot_no"], b["qty_base"]) for b in sale["lines"][0]["batches"]]
    check(
        lots == [("S3EARLY", strip), ("S3LATE", strip)],
        f"earliest-expiring batch first, split across batches ({lots})",
    )
    receipt_body = json.dumps({"type": "receipt_80mm", "invoice_id": sale["id"]}).encode()
    status, pdf, ctype = call_raw("POST", "/api/documents/v1/render", receipt_body, ctoken,
                                  {"Content-Type": "application/json"})  # fmt: skip
    if check(status == 200 and pdf.startswith(b"%PDF"), f"80mm receipt PDF ({status})"):
        out = Path(tempfile.gettempdir()) / "pharmacy-smoke-receipt.pdf"
        out.write_bytes(pdf)
        print(f"        open {out}")

    # 2. the same Idempotency-Key does not sell twice
    status, again = sell(
        [line("PARA500", "strip", 2), line("CETI10", "strip", 1)], payments, headers=sale_key
    )
    _, stock = call("GET", f"{inv}/stock?branch_id={bid}&q=PARA500", token=token)
    on_hand = sum(i["qty_on_hand"] for i in stock.get("items", []))
    check(again.get("id") == sale["id"] and on_hand == strip + box - 2 * strip,
          f"same Idempotency-Key: same invoice, sold once (PARA500 left {on_hand})")  # fmt: skip

    # 3. two tills, the last ORS sachet, at the same moment
    ors = [line("ORS", "sachet", 1)]
    cash = [{"method": "cash", "currency": "USD", "amount": "1.00"}]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda t: sell(ors, cash, tok=t), [ctoken, token]))
    codes = sorted(str(st) if st == 201 else r.get("code", str(st)) for st, r in results)
    _, stock = call("GET", f"{inv}/stock?branch_id={bid}&q=ORS", token=token)
    left = sum(i["qty_on_hand"] for i in stock.get("items", []))
    check(codes == ["201", "OUT_OF_STOCK"] and left == 0, f"last unit sold once, the other till gets OUT_OF_STOCK "
          f"({codes}, left {left})")  # fmt: skip

    # 4. Rx-only and controlled refused
    status, r = sell([line("AMOX500", "strip", 1)], cash)
    check(
        status == 422 and r.get("code") == "RX_REQUIRED", f"Rx-only refused -> RX_REQUIRED ({r.get('code')})"
    )
    status, r = sell([line("DIAZ5", "strip", 1)], cash)
    check(status == 422 and r.get("code") == "RX_REQUIRED",
          f"controlled without an Rx refused -> RX_REQUIRED ({r.get('code')})")  # fmt: skip

    # 5. credit: over the limit refused with nothing reserved; within it fine; a payment lowers it
    status, customer = call("POST", f"{cust}/customers", {"phone": f"097{random.randint(1000000, 9999999)}",
                            "name": "Smoke customer", "credit_limit": "2.00"}, token=token)  # fmt: skip
    if check(status == 201, f"customer with a 2.00 USD credit limit -> 201 (got {status})"):
        credit = [{"method": "credit", "currency": "USD", "amount": str(2 * ceti_strip)}]

        def over_limit():
            st, r = sell([line("CETI10", "strip", 2)], credit, customer_id=customer["id"])
            return (st, r) if r.get("code") != "CUSTOMER_REQUIRED" else None

        status, r = wait_for(over_limit, tries=30) or (0, {})
        _, stock = call("GET", f"{inv}/stock?branch_id={bid}&q=CETI10", token=token)
        reserved = sum(i["qty_reserved"] for i in stock.get("items", []))
        check(status == 422 and r.get("code") == "CREDIT_LIMIT_EXCEEDED" and reserved == 0,
              f"credit over the limit refused, nothing reserved ({r.get('code')}, reserved {reserved})")  # fmt: skip
        status, on_credit = sell([line("CETI10", "strip", 1)], [{"method": "credit", "amount": str(ceti_strip)}],
                                 customer_id=customer["id"])  # fmt: skip
        check(
            status == 201, f"credit sale within the limit -> 201 (got {status} {on_credit.get('code', '')})"
        )
        status, payment = call("POST", f"{cust}/customer-payments", {"customer_id": customer["id"], "branch_id": bid,
                               "method": "ABA", "amount": "1.00"}, token=ctoken, headers=key())  # fmt: skip
        _, c = call("GET", f"{cust}/customers/{customer['id']}", token=token)
        allocated = [a["invoice_no"] for a in payment.get("allocations", [])]
        check(status == 201 and Decimal(c.get("balance") or "0") == ceti_strip - 1 and allocated == [on_credit.get("number")],
              f"customer payment lowers the balance to {c.get('balance')}, oldest invoice first ({allocated})")  # fmt: skip

    # 6. cancel: cashier 403; owner → stock back to the same batches
    status, _ = call("POST", f"{sales}/invoices/{sale['id']}/cancel", {"reason": "smoke"}, token=ctoken)
    check(status == 403, f"cashier cancelling -> 403 (got {status})")
    status, cancelled = call(
        "POST", f"{sales}/invoices/{sale['id']}/cancel", {"reason": "smoke test"}, token=token
    )
    _, stock = call("GET", f"{inv}/stock?branch_id={bid}&q=PARA500", token=token)
    lots = {b["lot_no"]: b["qty_on_hand"] for i in stock.get("items", []) for b in i["batches"]}
    check(status == 200 and lots == {"S3EARLY": strip, "S3LATE": box},
          f"cancel puts the stock back into the same batches ({lots})")  # fmt: skip

    # 7. partial return
    status, two = sell([line("PARA500", "strip", 2)], [{"method": "cash", "currency": "USD", "amount": str(2 * para_strip)}],
                       tok=token)  # fmt: skip
    status, ret = call("POST", f"{sales}/invoices/{two.get('id')}/returns", {
        "lines": [{"invoice_line_id": two["lines"][0]["id"], "qty": 1}], "refund_method": "cash",
        "reason": "smoke test"}, token=token, headers=key())  # fmt: skip
    check(status == 201 and ret.get("number", "").endswith("-RT-" + str(today.year) + "-000001"),
          f"partial return -> 201 ({ret.get('number')} refund {ret.get('refund_usd')})")  # fmt: skip

    # 8. /internal is not reachable through Traefik
    status, _ = call("POST", "/internal/v1/reservations", {}, token=token)
    check(status == 404, f"/internal/v1 not routed by Traefik -> 404 (got {status})")

    for action in ("exchange_rate.changed", "invoice.created", "invoice.cancelled", "invoice.returned",
                   "credit.charged"):  # fmt: skip

        def logged(action=action):
            _, log = call("GET", f"/api/auth/v1/audit-logs?action={action}&size=1", token=token)
            return log.get("total")

        check(bool(wait_for(logged)), f"User Log shows {action}")
    if customer.get("id"):
        call("POST", f"{cust}/customers/{customer['id']}/deactivate", {"reason": "smoke test"}, token=token)
    remove_test_cashier(token, bid, cashier)


def totp_now(secret: str) -> str:
    """The current authenticator code for a base32 secret (RFC 6238, standard library only)."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def make_test_manager(token: str, bid: str, pin: str) -> tuple[dict, str] | None:
    """A branch manager for the test branch, with 2FA turned on and a PIN: (user, access token)."""
    phone, password = f"09{random.randint(1000000, 9999999)}", f"smoke-{random.randint(100000, 999999)}"
    status, manager = call("POST", "/api/auth/v1/users", {"name": "Smoke manager", "phone": phone,
                           "password": password, "role": "branch_manager", "branch_ids": [bid]}, token=token)  # fmt: skip
    if not check(status == 201, f"test branch manager created -> 201 (got {status} {manager.get('code', '')})"):
        return None
    data = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})[1]
    secret = call("POST", "/api/auth/v1/2fa/setup", token=data.get("access_token"))[1].get("secret", "")
    status, data = call("POST", "/api/auth/v1/2fa/enable", {"code": totp_now(secret)}, token=data.get("access_token"))
    if not check(status == 200, f"manager turns on 2FA -> 200 (got {status} {data.get('code', '')})"):
        return None
    status, _ = call("PUT", "/api/auth/v1/me/pin", {"password": password, "pin": pin}, token=data["access_token"])
    check(status == 204, f"manager sets a PIN -> 204 (got {status})")
    return manager, data["access_token"]


def tiny_png() -> bytes:
    """A 2×2 white PNG, made with the standard library."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + b"\xff\xff\xff" * 2 for _ in range(2))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))  # fmt: skip


def s4_checks(token: str) -> None:
    cat, inv, sales, rxp = "/api/catalog/v1", "/api/inventory/v1", "/api/sales/v1", "/api/prescription/v1"
    _, found = call("GET", f"{cat}/medicines/search?q=AMOX500", token=token)
    amox = next((x for x in found.get("items", []) if x["sku"] == "AMOX500"), None)
    if amox is None:
        check(False, "sample product AMOX500 exists (run the S1b step first)")
        return
    packs = {p["name"]: p for p in amox["pack_units"]}
    strip = packs["strip"]["qty_in_base"]
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, cphone, cpassword = made
    today = date.today()

    def key() -> dict:
        return {"Idempotency-Key": str(uuid.uuid4())}

    phone, password = f"09{random.randint(1000000, 9999999)}", f"smoke-{random.randint(100000, 999999)}"
    status, pharmacist = call("POST", "/api/auth/v1/users", {"name": "Smoke pharmacist", "phone": phone,
                              "password": password, "role": "pharmacist", "is_pharmacist": True,
                              "branch_ids": [bid]}, token=token)  # fmt: skip
    if not check(status == 201, f"test pharmacist created -> 201 (got {status} {pharmacist.get('code', '')})"):
        return remove_test_cashier(token, bid, cashier)
    ptoken = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})[1].get("access_token", "")
    ctoken = call("POST", "/api/auth/v1/login", {"phone": cphone, "password": cpassword})[1].get("access_token", "")
    patient, doctor = {}, {}
    try:
        stock = {"branch_id": bid, "reason": "Smoke test S4", "lines": [{
            "medicine_id": amox["id"], "pack_unit_id": packs["strip"]["id"], "lot_no": "S4LOT",
            "expiry_date": (today + timedelta(days=400)).isoformat(), "qty": 5, "unit_cost": "0.50"}]}  # fmt: skip

        def stock_in():
            st, out = call("POST", f"{inv}/stock-in", stock, token=token, headers=key())
            return (st, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, _ = wait_for(stock_in, tries=30) or (0, {})
        check(status == 201, f"stock-in 5 strips of AMOX500 -> 201 (got {status})")
        call("PUT", f"{sales}/exchange-rates/{bid}", {"khr_per_usd": 4100}, token=token)

        # patient (allergic to amoxicillin) and doctor
        def new_patient():
            st, out = call("POST", f"{rxp}/patients", {"branch_id": bid, "name_en": "Smoke Patient",
                           "name_km": "អ្នកជំងឺ តេស្ត", "sex": "female", "phone": f"097{random.randint(1000000, 9999999)}",
                           "allergies": [{"kind": "ingredient", "value": "Amoxicillin", "note": "smoke test"}]},
                           token=ptoken)  # fmt: skip
            return (st, out) if out.get("code") != "UNKNOWN_BRANCH" else None

        status, patient = wait_for(new_patient, tries=30) or (0, {})
        if not check(status == 201, f"pharmacist creates a patient with an allergy -> 201 (got {status} "
                     f"{patient.get('code', '')}{'; run make resync' if patient.get('code') else ''})"):  # fmt: skip
            return
        status, doctor = call("POST", f"{rxp}/doctors", {"name": "Dr Smoke", "licence_no": f"SMOKE-{uuid.uuid4().hex[:8]}",
                              "clinic": "Smoke clinic"}, token=ptoken)  # fmt: skip
        check(status == 201, f"doctor -> 201 (got {status})")
        status, _ = call("GET", f"{rxp}/patients", token=ctoken)
        check(status == 403, f"cashier cannot list patients -> 403 (got {status})")

        # prescription: 2 strips, no repeats
        def new_rx():
            st, out = call("POST", f"{rxp}/prescriptions", {"branch_id": bid, "patient_id": patient["id"],
                           "doctor_id": doctor["id"], "issued_on": today.isoformat(), "rx_no": "SMOKE-1",
                           "items": [{"medicine_id": amox["id"], "qty_base": 2 * strip, "dosage": "1 capsule",
                                      "frequency": "3 times a day", "duration_days": 7}]}, token=ptoken)  # fmt: skip
            return (st, out) if out.get("code") != "UNKNOWN_MEDICINE" else None

        status, rx = wait_for(new_rx, tries=30) or (0, {"code": "UNKNOWN_MEDICINE"})
        if not check(status == 201, f"Rx for {2 * strip} AMOX500 -> 201 (got {status} {rx.get('code', '')}"
                     f"{'; run make resync' if rx.get('code') else ''})"):  # fmt: skip
            return
        status, rx = call("POST", f"{rxp}/prescriptions/{rx['id']}/activate", token=ptoken)
        check(status == 200 and rx.get("status") == "active", f"Rx {rx.get('number')} activated, valid until "
              f"{rx.get('valid_until')}")  # fmt: skip
        item = rx["items"][0]["id"]

        # Rx image: upload, read back through the service
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="rx-photo.png"\r\n'
                "Content-Type: image/png\r\n\r\n").encode() + tiny_png() + f"\r\n--{boundary}--\r\n".encode()  # fmt: skip
        status, raw, _ = call_raw("POST", f"{rxp}/prescriptions/{rx['id']}/attachments", body, ptoken,
                                  {"Content-Type": f"multipart/form-data; boundary={boundary}"})  # fmt: skip
        att = json.loads(raw) if status == 201 else {}
        check(status == 201 and att.get("content_type") == "image/png", f"Rx image uploaded -> 201 (got {status})")
        url = f"{BASE}{rxp}/prescriptions/{rx['id']}/attachments/{att.get('id')}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {ptoken}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                h, data = resp.headers, resp.read()
            check(data.startswith(b"\x89PNG") and h.get("Content-Type") == "image/png"
                  and h.get("X-Content-Type-Options") == "nosniff" and h.get("Cache-Control") == "no-store"
                  and (h.get("Content-Disposition") or "").startswith("inline"),
                  "Rx image streamed by the service (image/png, nosniff, no-store, inline)")  # fmt: skip
        except urllib.error.HTTPError as err:
            check(False, f"Rx image download -> {err.code}")
        status, _, _ = call_raw("GET", f"{rxp}/prescriptions/{rx['id']}/attachments/{att.get('id')}", None, ctoken)
        check(status == 403, f"cashier opening the Rx image -> 403 (got {status})")
        status, _, _ = call_raw("GET", "/rx-files/", None, token)
        check(status == 404, f"no route to the file store through Traefik -> 404 (got {status})")

        # selling against the Rx
        def sell(qty, tok, **extra):
            return call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [{
                "medicine_id": amox["id"], "pack_unit_id": packs["strip"]["id"], "qty": qty, "rx_item_id": item,
                **extra}], "payments": [{"method": "cash", "currency": "USD", "amount": "20.00"}]},
                token=tok, headers=key())  # fmt: skip

        status, r = sell(1, ctoken)
        check(status == 403 and r.get("code") == "PHARMACIST_REQUIRED",
              f"cashier dispensing an Rx -> 403 PHARMACIST_REQUIRED ({r.get('code')})")  # fmt: skip

        def first_try():
            st, out = sell(1, ptoken)
            return (st, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, r = wait_for(first_try, tries=30) or (0, {})
        if status == 201:
            check(False, "allergy warning: AMOX500 has no active ingredients in the prescription service "
                  "(run make resync once after upgrading to S4)")  # fmt: skip
            sale = r
        else:
            check(status == 409 and r.get("code") == "ALLERGY_WARNING",
                  f"allergy blocks the sale -> 409 ALLERGY_WARNING ({r.get('code')}: {r.get('message', '')[:60]})")  # fmt: skip
            status, sale = sell(1, ptoken, allergy_override_reason="Smoke test: doctor confirmed")
            line = sale.get("lines", [{}])[0]
            check(status == 201 and line.get("allergy_override_reason") == "Smoke test: doctor confirmed"
                  and line.get("prescription_number") == rx["number"],
                  f"pharmacist overrides with a reason -> 201 ({sale.get('number')})")  # fmt: skip

        def remaining():
            _, out = call("GET", f"{rxp}/prescriptions/{rx['id']}/remaining", token=ptoken)
            left = out.get("items", [{}])[0].get("remaining_base")
            return out if left == strip and out.get("status") == "partly_dispensed" else None

        left = wait_for(remaining, tries=30)
        check(bool(left), f"after selling 1 strip the Rx shows {strip} remaining, partly dispensed")
        status, r = sell(2, ptoken, allergy_override_reason="Smoke test")
        check(status == 422 and r.get("code") == "RX_QUANTITY_EXCEEDED",
              f"selling more than the Rx allows -> 422 RX_QUANTITY_EXCEEDED ({r.get('code')})")  # fmt: skip

        # dispensing label + Rx summary
        label = json.dumps({"type": "dispensing_label", "invoice_id": sale.get("id"), "lang": "km"}).encode()
        status, pdf, _ = call_raw("POST", "/api/documents/v1/render", label, ptoken,
                                  {"Content-Type": "application/json"})  # fmt: skip
        if check(status == 200 and pdf.startswith(b"%PDF"), f"dispensing label PDF, 70×40 mm ({status})"):
            out = Path(tempfile.gettempdir()) / "pharmacy-smoke-dispensing-label.pdf"
            out.write_bytes(pdf)
            print(f"        open {out}")
        summary_body = json.dumps({"type": "rx_summary", "patient_id": patient["id"]}).encode()
        status, pdf, _ = call_raw("POST", "/api/documents/v1/render", summary_body, ptoken,
                                  {"Content-Type": "application/json"})  # fmt: skip
        if check(status == 200 and pdf.startswith(b"%PDF"), f"Rx summary PDF ({status})"):
            out = Path(tempfile.gettempdir()) / "pharmacy-smoke-rx-summary.pdf"
            out.write_bytes(pdf)
            print(f"        open {out}")
        call("GET", f"{rxp}/patients/{patient['id']}", token=ptoken)

        for action in ("patient.created", "patient.viewed", "prescription.created", "rx_attachment.viewed",
                       "dispensing.allergy_override"):  # fmt: skip

            def logged(action=action):
                _, log = call("GET", f"/api/auth/v1/audit-logs?action={action}&size=1", token=token)
                return log.get("total")

            check(bool(wait_for(logged)), f"User Log shows {action}")
    finally:
        if patient.get("id"):
            call("POST", f"{rxp}/patients/{patient['id']}/deactivate", {"reason": "smoke test"}, token=token)
        if doctor.get("id"):
            call("POST", f"{rxp}/doctors/{doctor['id']}/deactivate", {"reason": "smoke test"}, token=token)
        call("POST", f"/api/auth/v1/users/{pharmacist['id']}/deactivate", {"reason": "smoke test"}, token=token)
        remove_test_cashier(token, bid, cashier)


def s5_checks(token: str) -> None:
    cat, inv, sales, rxp = "/api/catalog/v1", "/api/inventory/v1", "/api/sales/v1", "/api/prescription/v1"
    ctl, cnt, auth = "/api/controlled/v1", "/api/stockcount/v1", "/api/auth/v1"
    _, found = call("GET", f"{cat}/medicines/search?q=DIAZ5", token=token)
    diaz = next((x for x in found.get("items", []) if x["sku"] == "DIAZ5"), None)
    if diaz is None:
        check(False, "sample product DIAZ5 exists (run the S1b step first)")
        return
    packs = {p["name"]: p for p in diaz["pack_units"]}
    strip = packs["strip"]["qty_in_base"]
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, _, _ = made
    today = date.today()

    def key() -> dict:
        return {"Idempotency-Key": str(uuid.uuid4())}

    people, toks = [], []
    for n, pin in ((1, "2468"), (2, "1357")):
        phone, password = f"09{random.randint(1000000, 9999999)}", f"smoke-{random.randint(100000, 999999)}"
        status, person = call("POST", f"{auth}/users", {"name": f"Smoke pharmacist {n}", "phone": phone,
                              "password": password, "role": "pharmacist", "is_pharmacist": True,
                              "branch_ids": [bid]}, token=token)  # fmt: skip
        if not check(status == 201, f"pharmacist {n} created -> 201 (got {status})"):
            return remove_test_cashier(token, bid, cashier)
        tok = call("POST", f"{auth}/login", {"phone": phone, "password": password})[1].get("access_token", "")
        status, _ = call("PUT", f"{auth}/me/pin", {"password": password, "pin": pin}, token=tok)
        check(status == 204, f"pharmacist {n} sets a PIN -> 204 (got {status})")
        people.append((person, pin))
        toks.append(tok)
    (p1, pin1), (p2, pin2) = people
    t1, t2 = toks
    patient, doctor = {}, {}

    def pin_token(action: str) -> str:
        return call("POST", f"{auth}/pin/verify", {"pin": pin1, "action": action}, token=t1)[1].get("pin_token", "")

    def witness_token(action: str, who: dict | None = None, pin: str | None = None) -> str:
        return call("POST", f"{auth}/pin/witness", {"witness_user_id": (who or p2)["id"], "pin": pin or pin2,
                    "action": action}, token=t1)[1].get("pin_token", "")  # fmt: skip

    made_manager = make_test_manager(token, bid, "8642")
    if made_manager is None:
        return remove_test_cashier(token, bid, cashier)
    manager = made_manager[0]
    people.append((manager, "8642"))

    def register() -> dict:
        return call("GET", f"{ctl}/register?branch_id={bid}&medicine_id={diaz['id']}", token=t1)[1]

    try:
        stock = {"branch_id": bid, "reason": "Smoke test S5", "lines": [{
            "medicine_id": diaz["id"], "pack_unit_id": packs["strip"]["id"], "lot_no": "S5LOT",
            "expiry_date": (today + timedelta(days=500)).isoformat(), "qty": 3, "unit_cost": "0.90"}]}  # fmt: skip

        def stock_in():
            st, out = call("POST", f"{inv}/stock-in", stock, token=token, headers=key())
            return (st, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, _ = wait_for(stock_in, tries=30) or (0, {})
        check(status == 201, f"stock-in 3 strips of DIAZ5 -> 201 (got {status})")
        got = wait_for(lambda: register() if len(register().get("entries", [])) >= 1 else None, tries=40)
        if not check(bool(got) and got["entries"][0]["entry_type"] == "receive"
                     and got["entries"][0]["balance_after"] == 3 * strip,
                     f"register shows the receipt, balance {3 * strip} (run make resync if it never comes)"):  # fmt: skip
            return
        call("PUT", f"{sales}/exchange-rates/{bid}", {"khr_per_usd": 4100}, token=token)

        # Rx for the controlled medicine (valid 7 days by default)
        def new_patient():
            st, out = call("POST", f"{rxp}/patients", {"branch_id": bid, "name_en": "Smoke S5 Patient",
                           "sex": "male", "phone": f"097{random.randint(1000000, 9999999)}"}, token=t1)  # fmt: skip
            return (st, out) if out.get("code") != "UNKNOWN_BRANCH" else None

        status, patient = wait_for(new_patient, tries=30) or (0, {})
        status, doctor = call("POST", f"{rxp}/doctors", {"name": "Dr Smoke S5", "licence_no":
                              f"S5-{uuid.uuid4().hex[:8]}"}, token=t1)  # fmt: skip
        status, rx = call("POST", f"{rxp}/prescriptions", {"branch_id": bid, "patient_id": patient.get("id"),
                          "doctor_id": doctor.get("id"), "issued_on": today.isoformat(),
                          "items": [{"medicine_id": diaz["id"], "qty_base": strip, "dosage": "1 tablet",
                                     "frequency": "at night"}]}, token=t1)  # fmt: skip
        call("POST", f"{rxp}/prescriptions/{rx.get('id')}/activate", token=t1)
        check(status == 201 and rx.get("valid_until") == (today + timedelta(days=7)).isoformat(),
              f"controlled Rx valid 7 days ({rx.get('valid_until')})")  # fmt: skip

        def sell(**extra):
            return call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [{
                "medicine_id": diaz["id"], "pack_unit_id": packs["strip"]["id"], "qty": 1,
                "rx_item_id": rx["items"][0]["id"], "patient_id_document": "SMOKE-ID-001"}],
                "payments": [{"method": "cash", "currency": "USD", "amount": "20.00"}], **extra},
                token=t1, headers=key())  # fmt: skip

        status, r = sell()
        check(status == 401 and r.get("code") == "PIN_REQUIRED", f"controlled sale without PIN -> 401 ({r.get('code')})")
        status, sale = sell(pin_token=pin_token("controlled.dispense"))
        check(status == 201 and sale["lines"][0].get("is_controlled"),
              f"controlled sale with Rx, patient ID and PIN -> 201 ({sale.get('number')})")  # fmt: skip

        # destroy one tablet with a witness
        batch = next((b["batch_id"] for i in call("GET", f"{inv}/stock?branch_id={bid}&q=DIAZ5", token=token)[1]
                      .get("items", []) for b in i["batches"]), None)  # fmt: skip
        body = {"branch_id": bid, "batch_id": batch, "kind": "destroy", "qty_base": 1, "reason": "Smoke: broken tablet",
                "destruction_method": "Crushed, witnessed"}  # fmt: skip
        status, r = call("POST", f"{ctl}/entries", {**body, "pin_token": pin_token("controlled.destroy")}, token=t1,
                         headers=key())  # fmt: skip
        check(status == 422 and r.get("code") == "WITNESS_REQUIRED", f"destroy without witness -> 422 ({r.get('code')})")
        status, r = call("POST", f"{ctl}/entries", {**body, "pin_token": pin_token("controlled.destroy"),
                         "witness_token": witness_token("controlled.destroy")}, token=t1, headers=key())  # fmt: skip
        check(status == 422 and r.get("code") == "WITNESS_INVALID",
              f"destroy witnessed by a pharmacist -> 422 WITNESS_INVALID ({r.get('code')})")  # fmt: skip
        status, r = call("POST", f"{ctl}/entries", {**body, "pin_token": pin_token("controlled.destroy"),
                         "witness_token": witness_token("controlled.destroy", manager, "8642")}, token=t1,
                         headers=key())  # fmt: skip
        check(status == 201 and r.get("witness_name") == "Smoke manager",
              f"destroy 1 tablet with the branch manager's PIN as witness -> 201 (got {status} {r.get('code', '')})")  # fmt: skip
        expected = 3 * strip - strip - 1
        got = wait_for(lambda: register() if len(register().get("entries", [])) >= 3 else None, tries=40) or {}
        kinds = [(e["entry_type"], e["balance_after"]) for e in got.get("entries", [])]
        check(kinds == [("receive", 3 * strip), ("dispense", 2 * strip), ("destroy", expected)],
              f"register: receive, dispense, destroy with running balance ({kinds})")  # fmt: skip
        last = (got.get("entries") or [{}])[-1]
        check(last.get("witness_name") == "Smoke manager", "the register names the witness")
        disp = next((e for e in got.get("entries", []) if e["entry_type"] == "dispense"), {})
        check(disp.get("prescription_number") == rx.get("number") and disp.get("patient_id_document") == "SMOKE-ID-001",
              "the dispense entry carries the Rx and the patient's ID")  # fmt: skip
        status, v = call("GET", f"{ctl}/register/verify?branch_id={bid}", token=t1)
        check(status == 200 and v.get("valid") is True, "hash chain verifies")
        pdf_body = json.dumps({"type": "controlled_register", "branch_id": bid}).encode()
        status, pdf, _ = call_raw("POST", "/api/documents/v1/render", pdf_body, t1, {"Content-Type": "application/json"})
        if check(status == 200 and pdf.startswith(b"%PDF"), f"register PDF ({status})"):
            out = Path(tempfile.gettempdir()) / "pharmacy-smoke-register.pdf"
            out.write_bytes(pdf)
            print(f"        open {out}")

        # stock take of controlled medicines: both pharmacists count (one tablet short), approve with PIN
        status, count = call("POST", f"{cnt}/counts", {"branch_id": bid, "scope": "controlled"}, token=t1)
        if check(status == 201 and len(count.get("lines", [])) == 1 and "snapshot_qty" not in count["lines"][0],
                 f"controlled stock take started, blind ({count.get('number')})"):  # fmt: skip
            line = count["lines"][0]
            for tok in (t1, t2):
                status, r = call("POST", f"{cnt}/counts/{count['id']}/entries",
                                 {"line_id": line["id"], "qty": expected - 1}, token=tok)  # fmt: skip
            check(r.get("status") == "agreed", f"two pharmacists counted the same -> agreed ({r.get('status')})")
            status, review = call("POST", f"{cnt}/counts/{count['id']}/submit", token=t1)
            check(status == 200 and review["lines"][0]["variance"] == -1, f"review shows a variance of -1 ({status})")
            status, r = call("POST", f"{cnt}/counts/{count['id']}/approve", {}, token=t1, headers=key())
            check(status == 401 and r.get("code") == "PIN_REQUIRED", "approving a controlled variance needs the PIN")
            status, r = call("POST", f"{cnt}/counts/{count['id']}/approve",
                             {"pin_token": pin_token("stockcount.approve")}, token=t1, headers=key())  # fmt: skip
            check(status == 200 and r.get("status") == "approved", f"stock take approved with PIN ({status})")
            got = wait_for(lambda: register() if len(register().get("entries", [])) >= 4 else None, tries=40) or {}
            last = (got.get("entries") or [{}])[-1]
            check(last.get("entry_type") == "count_adjust" and last.get("balance_after") == expected - 1,
                  f"the stock take reached stock and the register (balance {last.get('balance_after')})")  # fmt: skip
        for action in ("user.pin_set", "invoice.created", "register.destroy", "stock_count.approved"):

            def logged(action=action):
                _, log = call("GET", f"{auth}/audit-logs?action={action}&size=1", token=token)
                return log.get("total")

            check(bool(wait_for(logged)), f"User Log shows {action}")
    finally:
        if patient.get("id"):
            call("POST", f"{rxp}/patients/{patient['id']}/deactivate", {"reason": "smoke test"}, token=token)
        if doctor.get("id"):
            call("POST", f"{rxp}/doctors/{doctor['id']}/deactivate", {"reason": "smoke test"}, token=token)
        for person, _ in people:
            call("POST", f"{auth}/users/{person['id']}/deactivate", {"reason": "smoke test"}, token=token)
        remove_test_cashier(token, bid, cashier)


def s6_checks(token: str) -> None:
    cat, inv, pur, docs = "/api/catalog/v1", "/api/inventory/v1", "/api/purchasing/v1", "/api/documents/v1/render"
    _, found = call("GET", f"{cat}/medicines/search?q=PARA500", token=token)
    para = next((x for x in found.get("items", []) if x["sku"] == "PARA500"), None)
    if para is None:
        check(False, "sample product PARA500 exists (run the S1b step first)")
        return
    packs = {p["name"]: p for p in para["pack_units"]}
    made_a, made_b = make_test_cashier(token), make_test_cashier(token)
    if made_a is None or made_b is None:
        return
    (a, cashier_a, _, _), (b, cashier_b, b_phone, b_password) = made_a, made_b
    today = date.today()
    supplier: dict = {}

    def key() -> dict:
        return {"Idempotency-Key": str(uuid.uuid4())}

    def on_hand(branch: str) -> int:
        _, out = call("GET", f"{inv}/stock?branch_id={branch}&q=PARA500", token=token)
        return sum(i["qty_on_hand"] for i in out.get("items", []))

    def in_transit() -> int:
        _, rows = call("GET", f"{inv}/transfers/in-transit?branch_id={a}", token=token)
        return sum(r["qty_base"] for r in rows if r["medicine_id"] == para["id"]) if isinstance(rows, list) else -1

    try:
        stock = {"branch_id": a, "reason": "Smoke test S6", "lines": [
            {"medicine_id": para["id"], "pack_unit_id": packs["strip"]["id"], "lot_no": "S6EARLY",
             "expiry_date": (today + timedelta(days=200)).isoformat(), "qty": 3, "unit_cost": "0.50"},
            {"medicine_id": para["id"], "pack_unit_id": packs["strip"]["id"], "lot_no": "S6LATE",
             "expiry_date": (today + timedelta(days=600)).isoformat(), "qty": 5, "unit_cost": "0.55"}]}  # fmt: skip

        def stock_in():
            st, out = call("POST", f"{inv}/stock-in", stock, token=token, headers=key())
            return (st, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, _ = wait_for(stock_in, tries=30) or (0, {})
        if not check(status == 201, f"stock-in PARA500 at branch A -> 201 (got {status})"):
            return
        strip = packs["strip"]["qty_in_base"]
        total = on_hand(a) + on_hand(b) + in_transit()

        # request → approve → pick (FEFO) → dispatch → receive short → resolve
        def ask():
            st, out = call("POST", f"{inv}/transfer-requests", {"from_branch_id": a, "to_branch_id": b,
                           "reason": "Smoke S6", "lines": [{"medicine_id": para["id"], "qty_base": 4 * strip}]},
                           token=token)  # fmt: skip
            return (st, out) if out.get("code") != "UNKNOWN_BRANCH" else None

        status, request = wait_for(ask, tries=30) or (0, {})
        check(status == 201, f"branch B requests 4 strips from A -> 201 ({request.get('number')})")
        status, t = call("POST", f"{inv}/transfer-requests/{request.get('id')}/approve", token=token)
        check(status == 200 and t.get("status") == "approved", f"A approves -> transfer {t.get('number')}")
        status, t = call("POST", f"{inv}/transfers/{t['id']}/pick", {}, token=token)
        lots = [(p["lot_no"], p["qty_base"]) for p in t.get("picks", [])]
        check(lots == [("S6EARLY", 3 * strip), ("S6LATE", strip)], f"picked FEFO, earliest expiry first ({lots})")
        status, t = call("POST", f"{inv}/transfers/{t['id']}/dispatch", {}, token=token, headers=key())
        check(status == 200 and t.get("status") == "dispatched" and in_transit() == 4 * strip,
              f"dispatched: {4 * strip} in transit, visible to both branches")  # fmt: skip
        note = json.dumps({"type": "transfer_note", "transfer_id": t["id"]}).encode()
        status, pdf, _ = call_raw("POST", docs, note, token, {"Content-Type": "application/json"})
        if check(status == 200 and pdf.startswith(b"%PDF"), f"transfer note PDF with QR code ({status})"):
            out = Path(tempfile.gettempdir()) / "pharmacy-smoke-transfer-note.pdf"
            out.write_bytes(pdf)
            print(f"        open {out}")
        btoken = call("POST", "/api/auth/v1/login", {"phone": b_phone, "password": b_password})[1].get("access_token")
        lines = [{"pick_id": p["id"], "qty_received": p["qty_base"] - (3 if p["lot_no"] == "S6LATE" else 0),
                  "location": "S6"} for p in t["picks"]]  # fmt: skip
        status, t = call("POST", f"{inv}/transfers/{t['id']}/receive", {"lines": lines}, token=btoken, headers=key())
        diffs = t.get("discrepancies", [])
        check(status == 200 and t.get("status") == "received" and [(d["kind"], d["qty_base"]) for d in diffs]
              == [("short", 3)], f"B's cashier receives 3 short -> a difference is open ({status})")  # fmt: skip
        status, t = call("POST", f"{inv}/transfers/{t['id']}/differences/{diffs[0]['id']}/resolve",
                         {"resolution": "write_off", "reason": "Smoke: lost on the way"}, token=token, headers=key())  # fmt: skip
        check(status == 200 and t.get("status") == "closed", f"difference written off -> transfer closed ({status})")
        after = on_hand(a) + on_hand(b) + in_transit()
        check(after == total - 3 and on_hand(b) == 4 * strip - 3,
              f"stock adds up: A {on_hand(a)} + B {on_hand(b)} + in transit {in_transit()} = {after} (was {total}, 3 lost)")  # fmt: skip

        # purchase request → PO group
        code = f"S6{random.randint(1000, 9999)}"
        status, supplier = call("POST", f"{pur}/suppliers", {"code": code, "name": f"Smoke supplier {code}",
                                "payment_terms_days": 30}, token=token)  # fmt: skip
        status, pr = call("POST", f"{pur}/purchase-requests", {"branch_id": a, "lines": [
            {"medicine_id": para["id"], "qty_base": 2 * packs["box"]["qty_in_base"], "reason": "Smoke S6"}]}, token=token)  # fmt: skip
        check(status == 201, f"purchase request at A -> 201 ({pr.get('number')})")
        status, pr = call("POST", f"{pur}/purchase-requests/{pr['id']}/approve", token=token)
        check(pr.get("status") == "approved", "purchase request approved")
        status, group = call("POST", f"{pur}/purchase-requests/to-purchase-orders", {"supplier_id": supplier["id"],
                             "lines": [{"request_line_id": pr["lines"][0]["id"], "pack_unit_id": packs["box"]["id"],
                                        "qty": 2, "unit_cost": "4.50"}]}, token=token)  # fmt: skip
        pos = group.get("purchase_orders", [])
        check(status == 201 and len(pos) == 1 and pos[0]["branch_id"] == a,
              f"turned into PO group {group.get('number')} with PO {pos[0]['number'] if pos else '?'}")  # fmt: skip
        _, pr = call("GET", f"{pur}/purchase-requests/{pr['id']}", token=token)
        check(pr.get("progress") == "ordered", f"the request shows its progress ({pr.get('progress')})")
        printout = json.dumps({"type": "purchase_order_group", "group_id": group.get("id")}).encode()
        status, pdf, _ = call_raw("POST", docs, printout, token, {"Content-Type": "application/json"})
        if check(status == 200 and pdf.startswith(b"%PDF"), f"PO group printout for the supplier ({status})"):
            out = Path(tempfile.gettempdir()) / "pharmacy-smoke-po-group.pdf"
            out.write_bytes(pdf)
            print(f"        open {out}")

        # re-order list for B
        call("PUT", f"{inv}/reorder-settings", {"branch_id": b, "medicine_id": para["id"], "min_qty": 50,
             "max_qty": 200}, token=token)  # fmt: skip
        status, rl = call("POST", f"{inv}/reorder-lists/run?branch_id={b}", token=token)
        line = next((x for x in rl.get("lines", []) if x["sku"] == "PARA500"), {})
        check(status == 200 and line.get("reorder_point") == 50 and line.get("suggested_qty", 0) > 0,
              f"re-order list for B suggests PARA500 ({status})")  # fmt: skip
        print(f"        re-order list {rl.get('run_date')} for branch B:")
        for x in rl.get("lines", []):
            source = f" · could come from another branch ({x['source_reason']}, {x['source_qty']})" if x.get(
                "source_branch_id") else ""  # fmt: skip
            print(f"          {x['sku']:<10} on hand {x['on_hand']:>5}  in transit {x['in_transit']:>4}  "
                  f"on order {x['on_order']:>4}  point {x['reorder_point']:>4}  suggest {x['suggested_qty']:>5} "
                  f"({x['pack_qty']} {x['pack_unit']}){source}")
        for action in ("transfer.dispatched", "transfer.received", "transfer.difference_resolved",
                       "purchase_request.approved", "po_group.created"):  # fmt: skip

            def logged(action=action):
                _, log = call("GET", f"/api/auth/v1/audit-logs?action={action}&size=1", token=token)
                return log.get("total")

            check(bool(wait_for(logged)), f"User Log shows {action}")
    finally:
        if supplier.get("id"):
            call("POST", f"{pur}/suppliers/{supplier['id']}/deactivate", {"reason": "smoke test"}, token=token)
        remove_test_cashier(token, a, cashier_a)
        remove_test_cashier(token, b, cashier_b)


def s7_checks(token: str) -> None:
    cat, inv, sales, cust = "/api/catalog/v1", "/api/inventory/v1", "/api/sales/v1", "/api/customers/v1"
    docs = "/api/documents/v1/render"
    products = {}
    for sku in ("PARA500", "CETI10", "ORS"):
        _, found = call("GET", f"{cat}/medicines/search?q={sku}", token=token)
        m = next((x for x in found.get("items", []) if x["sku"] == sku), None)
        if m is None:
            check(False, f"sample product {sku} exists (run the S1b step first)")
            return
        products[sku] = (m, {p["name"]: p for p in m["pack_units"]})
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, phone, password = made
    today = date.today()
    promo: dict = {}
    hamper: dict = {}
    customer: dict = {}

    def key() -> dict:
        return {"Idempotency-Key": str(uuid.uuid4())}

    def line(sku: str, pack: str, qty: int) -> dict:
        m, packs = products[sku]
        return {"medicine_id": m["id"], "pack_unit_id": packs[pack]["id"], "qty": qty}

    def reserved(sku: str) -> int:
        _, out = call("GET", f"{inv}/stock?branch_id={bid}&q={sku}", token=token)
        return sum(i["qty_reserved"] for i in out.get("items", []))

    def stock_in_line(sku: str, pack: str, qty: int) -> dict:
        return {**line(sku, pack, qty), "lot_no": f"S7{sku}", "unit_cost": "0.05",
                "expiry_date": (today + timedelta(days=400)).isoformat()}  # fmt: skip

    try:
        body = {"branch_id": bid, "reason": "Smoke test S7", "lines": [stock_in_line("PARA500", "box", 2),
                stock_in_line("CETI10", "box", 2), stock_in_line("ORS", "box", 1)]}  # fmt: skip

        def stock_in():
            st, out = call("POST", f"{inv}/stock-in", body, token=token, headers=key())
            return (st, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, _ = wait_for(stock_in, tries=30) or (0, {})
        if not check(status == 201, f"stock-in for the test branch -> 201 (got {status})"):
            return
        call("PUT", f"{sales}/exchange-rates/{bid}", {"khr_per_usd": 4100}, token=token)
        ctoken = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})[1].get("access_token", "")
        para_strip = Decimal(products["PARA500"][1]["strip"]["sell_price"])

        # 1. suspend on one till, resume on another (another user of the branch)
        def suspend():
            st, out = call("POST", f"{sales}/carts/suspend", {"branch_id": bid, "note": "customer went to the ATM",
                           "lines": [line("PARA500", "strip", 2)]}, token=ctoken, headers=key())  # fmt: skip
            return (st, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, cart = wait_for(suspend, tries=30) or (0, {})
        check(status == 201 and cart.get("status") == "suspended", f"cashier suspends a cart -> {cart.get('number')}")
        _, carts = call("GET", f"{sales}/carts?branch_id={bid}", token=token)
        check(any(c["id"] == cart.get("id") for c in carts) if isinstance(carts, list) else False,
              "the owner sees it in the branch's suspended carts")  # fmt: skip
        status, resumed = call("POST", f"{sales}/carts/{cart.get('id')}/resume", token=token, headers=key())
        check(status == 200 and Decimal(resumed.get("total", "0")) == 2 * para_strip and resumed.get("changes") == [],
              f"resumed on another till: re-priced {resumed.get('total')}, changes {resumed.get('changes')}")  # fmt: skip

        # 2. buy 2 get 1 on ORS sachets (this branch only)
        code = f"S7B2G1{random.randint(1000, 9999)}"
        ors = products["ORS"][0]
        status, promo = call("POST", f"{cat}/promotions", {"code": code, "name": "Smoke ORS buy 2 get 1",
                             "type": "buy_x_get_y", "buy_qty": 2, "get_qty": 1, "medicine_ids": [ors["id"]],
                             "branch_ids": [bid]}, token=token)  # fmt: skip
        check(status == 201, f"promotion {code} buy 2 get 1 on ORS -> 201 (got {status} {promo.get('code', '')})")
        sachet = Decimal(products["ORS"][1]["sachet"]["sell_price"])

        def priced():
            _, out = call("POST", f"{sales}/carts/price", {"branch_id": bid, "lines": [line("ORS", "sachet", 3)]},
                          token=ctoken)  # fmt: skip
            return out if Decimal(out.get("discount", "0")) > 0 else None

        cart_price = wait_for(priced, tries=30) or {}
        check(Decimal(cart_price.get("total", "-1")) == 2 * sachet, f"3 sachets cost 2: {cart_price.get('total')}")
        status, b2g1 = call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [line("ORS", "sachet", 3)],
                            "payments": [{"method": "cash", "amount": str(2 * sachet)}]}, token=ctoken, headers=key())  # fmt: skip
        first = (b2g1.get("lines") or [{}])[0]
        check(status == 201 and Decimal(first.get("promo_discount", "0")) == sachet and first.get("promotion_ids"),
              f"buy 2 get 1 sale {b2g1.get('number')}: discount {first.get('promo_discount')} stored on the line")  # fmt: skip

        # 3. a hamper: no stock of its own, its components FEFO
        para, ceti = products["PARA500"][0], products["CETI10"][0]
        hsku = f"S7KIT{random.randint(1000, 9999)}"
        status, hamper = call("POST", f"{cat}/hampers", {"sku": hsku, "name": "Smoke cold kit", "price": "3.00",
                              "components": [{"medicine_id": para["id"], "qty_base": 10},
                                             {"medicine_id": ceti["id"], "qty_base": 5}]}, token=token)  # fmt: skip
        check(status == 201 and hamper.get("kind") == "hamper", f"hamper {hsku} (10 PARA500 + 5 CETI10) -> {status}")
        hpack = (hamper.get("pack_units") or [{}])[0].get("id")

        def available():
            _, out = call("GET", f"{inv}/hampers/{hamper.get('id')}/availability?branch_id={bid}", token=token)
            return out if out.get("available") else None

        avail = wait_for(available, tries=30) or {}
        check(avail.get("available", 0) > 0, f"hampers available = lowest component: {avail.get('available')}")

        def sell_hamper():
            st, out = call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [{"medicine_id": hamper.get("id"),
                           "pack_unit_id": hpack, "qty": 1}], "payments": [{"method": "cash", "amount": "3.00"}]},
                           token=ctoken, headers=key())  # fmt: skip
            return (st, out) if out.get("code") != "UNKNOWN_MEDICINE" else None

        status, kit = wait_for(sell_hamper, tries=30) or (0, {})
        batches = {b.get("lot_no"): b["qty_base"] for b in (kit.get("lines") or [{}])[0].get("batches", [])}
        check(status == 201 and batches == {"S7PARA500": 10, "S7CETI10": 5},
              f"hamper sold {kit.get('number')}: components taken from their batches {batches}")  # fmt: skip

        # 4. sale order: quote → order with reservation + deposit → partly invoiced → PDF
        status, customer = call("POST", f"{cust}/customers", {"phone": f"097{random.randint(1000000, 9999999)}",
                                "name": "Smoke S7 clinic"}, token=token)  # fmt: skip

        def make_quote():
            st, out = call("POST", f"{sales}/sale-orders", {"branch_id": bid, "customer_id": customer.get("id"),
                           "lines": [line("PARA500", "strip", 2)]}, token=ctoken)  # fmt: skip
            return (st, out) if out.get("code") != "CUSTOMER_REQUIRED" else None

        status, order = wait_for(make_quote, tries=30) or (0, {})
        check(status == 201 and order.get("status") == "quote", f"quote {order.get('number')} -> {status}")
        before = reserved("PARA500")
        status, order = call("POST", f"{sales}/sale-orders/{order.get('id')}/confirm", {"reserve": True,
                             "deposit": {"method": "cash", "amount": str(para_strip)}}, token=ctoken, headers=key())  # fmt: skip
        strip = products["PARA500"][1]["strip"]["qty_in_base"]
        check(status == 200 and order.get("status") == "ordered" and reserved("PARA500") == before + 2 * strip,
              f"ordered with a {order.get('deposit_usd')} deposit, 2 strips reserved")  # fmt: skip
        status, part = call("POST", f"{sales}/sale-orders/{order.get('id')}/invoice", {
            "lines": [{"order_line_id": order["lines"][0]["id"], "qty": 1}],
            "payments": [{"method": "deposit", "amount": str(para_strip), "deposit_id": order.get("deposit_id")}]},
            token=ctoken, headers=key())  # fmt: skip
        _, order = call("GET", f"{sales}/sale-orders/{order.get('id')}", token=ctoken)
        check(status == 201 and order.get("status") == "partly_fulfilled" and reserved("PARA500") == before + strip,
              f"1 strip invoiced {part.get('number')} paid by the deposit; 1 strip still reserved")  # fmt: skip
        pdf_body = json.dumps({"type": "sale_order", "sale_order_id": order.get("id")}).encode()
        status, pdf, _ = call_raw("POST", docs, pdf_body, ctoken, {"Content-Type": "application/json"})
        if check(status == 200 and pdf.startswith(b"%PDF"), f"sale order PDF ({status})"):
            out = Path(tempfile.gettempdir()) / "pharmacy-smoke-sale-order.pdf"
            out.write_bytes(pdf)
            print(f"        open {out}")
        status, order = call("POST", f"{sales}/sale-orders/{order.get('id')}/cancel", {"reason": "smoke test"},
                             token=ctoken)  # fmt: skip
        check(status == 200 and reserved("PARA500") == before, "rest of the order cancelled, reservation released")

        # 5. commission: a 5 % rule, a sale, the report and its drill-down
        status, rule = call("POST", f"{sales}/commission/rules", {"name": "Smoke 5 %", "kind": "percent",
                            "value": "5", "scope": "all", "branch_id": bid, "starts_on": today.replace(day=1).isoformat()},
                            token=token)  # fmt: skip
        check(status == 201, f"commission rule 5 % for the test branch -> {status}")
        status, sale = call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [line("CETI10", "strip", 1)],
                            "payments": [{"method": "cash", "amount": "10.00"}]}, token=ctoken, headers=key())  # fmt: skip
        month = today.replace(day=1).isoformat()
        _, report = call("GET", f"{sales}/commission/report?branch_id={bid}&month={month}", token=token)
        mine = next((s for s in report.get("staff", []) if s["staff_id"] == cashier["id"]), {})
        check(Decimal(mine.get("commission", "0")) > 0, f"commission report: cashier earned {mine.get('commission')}")
        print(f"        commission {month} for the test branch ({report.get('status')}):")
        for s in report.get("staff", []):
            print(f"          staff {s['staff_id'][:8]}…  net {s['net_usd']:>8}  commission {s['commission']:>6}"
                  f"  ({s['lines']} lines)")
        _, drill = call("GET", f"{sales}/commission/report/{cashier['id']}?branch_id={bid}&month={month}", token=ctoken)
        check(isinstance(drill, list) and any(x["invoice_number"] == sale.get("number") for x in drill),
              "the cashier sees their own lines (drill-down)")  # fmt: skip
        status, _ = call("GET", f"{sales}/commission/report?branch_id={bid}&month={month}&staff_id={uuid.uuid4()}",
                         token=ctoken)  # fmt: skip
        check(status == 403, f"…but not someone else's -> 403 (got {status})")
        if rule.get("id"):
            call("POST", f"{sales}/commission/rules/{rule['id']}/deactivate", token=token)

        for action in ("cart.suspended", "cart.resumed", "promotion.created", "sale_order.ordered",
                       "sale_order.invoiced", "commission_rule.created"):  # fmt: skip

            def logged(action=action):
                _, log = call("GET", f"/api/auth/v1/audit-logs?action={action}&size=1", token=token)
                return log.get("total")

            check(bool(wait_for(logged)), f"User Log shows {action}")
    finally:
        if promo.get("id"):
            call("POST", f"{cat}/promotions/{promo['id']}/deactivate", token=token)
        if hamper.get("id"):
            call("POST", f"{cat}/medicines/{hamper['id']}/deactivate", {"reason": "smoke test"}, token=token)
        if customer.get("id"):
            call("POST", f"{cust}/customers/{customer['id']}/deactivate", {"reason": "smoke test"}, token=token)
        remove_test_cashier(token, bid, cashier)


def s8_checks(token: str) -> None:
    cat, inv, sales, rep, notif = ("/api/catalog/v1", "/api/inventory/v1", "/api/sales/v1", "/api/reports/v1",
                                   "/api/notifications/v1")  # fmt: skip
    _, found = call("GET", f"{cat}/medicines/search?q=PARA500", token=token)
    para = next((x for x in found.get("items", []) if x["sku"] == "PARA500"), None)
    if para is None:
        check(False, "sample product PARA500 exists (run the S1b step first)")
        return
    packs = {p["name"]: p for p in para["pack_units"]}
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, phone, password = made
    today = date.today()

    def key() -> dict:
        return {"Idempotency-Key": str(uuid.uuid4())}

    try:
        body = {"branch_id": bid, "reason": "Smoke test S8", "lines": [
            {"medicine_id": para["id"], "pack_unit_id": packs["box"]["id"], "lot_no": "S8A", "unit_cost": "2.00",
             "expiry_date": (today + timedelta(days=400)).isoformat(), "qty": 2}]}  # fmt: skip

        def stock_in():
            st, out = call("POST", f"{inv}/stock-in", body, token=token, headers=key())
            return (st, out) if out.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, _ = wait_for(stock_in, tries=30) or (0, {})
        if not check(status == 201, f"stock-in for the test branch -> 201 (got {status})"):
            return
        call("PUT", f"{sales}/exchange-rates/{bid}", {"khr_per_usd": 4100}, token=token)
        ctoken = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})[1].get("access_token", "")
        strip = Decimal(packs["strip"]["sell_price"])
        line = {"medicine_id": para["id"], "pack_unit_id": packs["strip"]["id"], "qty": 2}
        _, usd = call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [line],
                      "payments": [{"method": "cash", "amount": str(2 * strip)}]}, token=ctoken, headers=key())  # fmt: skip
        riel = int((2 * strip * 4100 / 100).to_integral_value(rounding="ROUND_CEILING")) * 100
        _, khr = call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [line],
                      "payments": [{"method": "cash", "currency": "KHR", "amount": str(riel)}]},
                      token=ctoken, headers=key())  # fmt: skip
        check(bool(usd.get("number") and khr.get("number")), f"two sales, USD and KHR: {usd.get('number')}, {khr.get('number')}")
        status, ret = call("POST", f"{sales}/invoices/{usd.get('id')}/returns", {
            "lines": [{"invoice_line_id": usd["lines"][0]["id"], "qty": 1}], "refund_method": "cash",
            "reason": "smoke test"}, token=token, headers=key())  # fmt: skip
        check(status == 201, f"one strip returned ({ret.get('number')})")
        total = Decimal(usd["total"]) + Decimal(khr["total"])

        def dashboard():
            _, d = call("GET", f"{rep}/dashboard?branch_id={bid}", token=token)
            today_ = d.get("today", {})
            return d if Decimal(today_.get("sales", "0")) == total and Decimal(today_.get("returns", "0")) > 0 else None

        dash = wait_for(dashboard, tries=40) or {}
        t = dash.get("today", {})
        check(bool(dash) and "gross_profit" in t,
              f"dashboard (owner): sales {t.get('sales')} USD / {t.get('sales_khr')} KHR, {t.get('invoices')} invoices, "
              f"returns {t.get('returns')}, gross profit {t.get('gross_profit')}")  # fmt: skip
        _, cd = call("GET", f"{rep}/dashboard?branch_id={bid}", token=ctoken)
        check("today" in cd and "gross_profit" not in cd["today"], "the cashier's dashboard has no profit")
        _, detail = call("GET", f"{rep}/sales/detail?branch_id={bid}&date_from={today}&date_to={today}", token=token)
        check(Decimal(detail.get("summary", {}).get("net", "-1")) == total and detail.get("summary", {}).get("invoices") == 2,
              f"Sale Detail totals = the invoices ({detail.get('summary', {}).get('net')} = {total})")  # fmt: skip
        for fmt, magic in (("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
            status, data, _ = call_raw("GET", f"{rep}/sales/detail?branch_id={bid}&format={fmt}", None, token)
            if check(status == 200 and data.startswith(magic), f"Sale Detail as {fmt.upper()} ({status})") and fmt == "pdf":
                out = Path(tempfile.gettempdir()) / "pharmacy-smoke-sale-detail.pdf"
                out.write_bytes(data)
                print(f"        open {out}")
        status, _ = call("GET", f"{rep}/sales/margin-by-item?branch_id={bid}", token=ctoken)
        check(status == 403, f"cashier asks for Sale Margin By Item -> 403 (got {status})")
        status, _ = call("GET", "/internal/v1/outbox", token=token)
        check(status == 404, f"/internal/v1/outbox not routed by Traefik -> 404 (got {status})")

        # Telegram: without a bot token nothing is sent, but every message is kept with its status
        call("PUT", f"{notif}/chats/owner", {"chat_id": "-1000000000001"}, token=token)
        status, r = call("POST", f"{notif}/test", {"target": "owner"}, token=token)
        check(status == 503 and r.get("code") == "TELEGRAM_NOT_CONFIGURED" or status == 200,
              f"test message -> {status} {r.get('code') or r.get('status')}")  # fmt: skip
        _, first = call("POST", f"{notif}/daily-summary/run", {}, token=token)
        _, second = call("POST", f"{notif}/daily-summary/run", {}, token=token)
        check(first.get("queued", 0) >= 1 and second.get("queued") == 0,
              f"daily summary run twice: {first.get('queued')} then {second.get('queued')} new")  # fmt: skip
        _, msgs = call("GET", f"{notif}/messages?kind=daily_summary&limit=1", token=token)
        if check(isinstance(msgs, list) and msgs, f"summary stored ({msgs[0]['status'] if msgs else '?'})"):
            print("        " + msgs[0]["text"].replace("\n", "\n        "))
        for action in ("report.exported", "telegram_chat.set"):

            def logged(action=action):
                _, log = call("GET", f"/api/auth/v1/audit-logs?action={action}&size=1", token=token)
                return log.get("total")

            check(bool(wait_for(logged)), f"User Log shows {action}")
    finally:
        remove_test_cashier(token, bid, cashier)


def s8b_checks(token: str) -> None:
    cat, inv, sales, pur, cust = ("/api/catalog/v1", "/api/inventory/v1", "/api/sales/v1", "/api/purchasing/v1",
                                  "/api/customers/v1")  # fmt: skip
    docs = "/api/documents/v1/render"
    found = {}
    for sku in ("PARA500", "AMOX500"):
        _, out = call("GET", f"{cat}/medicines/search?q={sku}", token=token)
        found[sku] = next((x for x in out.get("items", []) if x["sku"] == sku), None)
    para, amox = found["PARA500"], found["AMOX500"]
    if para is None or amox is None:
        check(False, "sample products PARA500 and AMOX500 exist (run the S1b step first)")
        return
    packs = {p["name"]: p for p in para["pack_units"]}
    made = make_test_cashier(token)
    if made is None:
        return
    bid, cashier, phone, password = made
    today = date.today()
    supplier: dict = {}
    customer: dict = {}
    recall: dict = {}

    def key() -> dict:
        return {"Idempotency-Key": str(uuid.uuid4())}

    def line(m: dict, pack: str, qty: int, **extra) -> dict:
        p = next(x for x in m["pack_units"] if x["name"] == pack)
        return {"medicine_id": m["id"], "pack_unit_id": p["id"], "qty": qty, **extra}

    def codes(p: dict, kind: str = "hard_stops") -> set:
        return {f["code"] for f in p.get(kind, [])} | {f["code"] for x in p.get("lines", []) for f in x[kind]}

    try:
        # stock from a supplier (so it can go back to them)
        sc = f"S8B{random.randint(1000, 9999)}"
        status, supplier = call("POST", f"{pur}/suppliers", {"code": sc, "name": f"Smoke supplier {sc}",
                                "payment_terms_days": 30}, token=token)  # fmt: skip

        def make_po():
            st, po = call("POST", f"{pur}/purchase-orders", {"branch_id": bid, "supplier_id": supplier.get("id"),
                          "lines": [{"medicine_id": para["id"], "pack_unit_id": packs["box"]["id"], "qty": 2,
                                     "unit_cost": "4.25"}]}, token=token)  # fmt: skip
            return (st, po) if po.get("code") not in ("UNKNOWN_BRANCH", "UNKNOWN_MEDICINE") else None

        status, po = wait_for(make_po, tries=30) or (0, {})
        call("POST", f"{pur}/purchase-orders/{po.get('id')}/send", token=token)
        status, _ = call("POST", f"{pur}/purchase-orders/{po.get('id')}/receive", {"lines": [
            {"po_line_id": po["lines"][0]["id"], "lot_no": "S8BLOT", "expiry_date": (today + timedelta(days=500)).isoformat(),
             "qty": 2}]}, token=token, headers=key())  # fmt: skip
        if not check(status == 201, f"2 boxes of PARA500 received from {sc} -> {status}"):
            return
        call("PUT", f"{sales}/exchange-rates/{bid}", {"khr_per_usd": 4100}, token=token)
        ctoken = call("POST", "/api/auth/v1/login", {"phone": phone, "password": password})[1].get("access_token", "")

        def batch_id():
            _, out = call("GET", f"{inv}/stock?branch_id={bid}&q=PARA500", token=token)
            return next((b["batch_id"] for i in out.get("items", []) for b in i["batches"] if b["lot_no"] == "S8BLOT"), None)

        batch = wait_for(batch_id, tries=30)
        check(bool(batch), "the lot is in stock at the test branch")

        # 1. cart preview: the same checks as the sale, nothing saved
        def preview(lines, tok=None, **extra):
            return call("POST", f"{sales}/carts/preview", {"branch_id": bid, "lines": lines, **extra},
                        token=tok or ctoken)  # fmt: skip

        status, p = preview([line(para, "strip", 2)])
        check(status == 200 and p.get("can_post") and p["lines"][0]["batches"][0]["lot_no"] == "S8BLOT"
              and p.get("total_khr"), f"preview: PARA500 can be sold from lot S8BLOT, {p.get('total')} USD / "
              f"{p.get('total_khr')} KHR")  # fmt: skip
        status, p = preview([line(amox, "strip", 1)])
        check("RX_REQUIRED" in codes(p) and not p.get("can_post"), f"preview: an Rx-only line needs the Rx ({codes(p)})")
        status, p = preview([line(amox, "strip", 1, rx_item_id=str(uuid.uuid4()))])
        check("PHARMACIST_REQUIRED" in codes(p), "preview as cashier with an Rx line -> PHARMACIST_REQUIRED")

        # 2. KHQR (fake provider on a development stack)
        price = Decimal(packs["strip"]["sell_price"]) * 2
        status, qr = call("POST", f"{sales}/payments/khqr", {"branch_id": bid, "amount": str(price), "currency": "USD"},
                          token=ctoken, headers=key())  # fmt: skip
        check(status == 201 and qr.get("status") == "pending" and qr.get("qr_string", "").startswith("000201"),
              f"KHQR for {price} USD -> pending ({status})")  # fmt: skip
        status, _ = call("POST", f"{sales}/payments/khqr/{qr.get('id')}/fake-pay", token=token)
        _, seen = call("GET", f"{sales}/payments/khqr/{qr.get('id')}", token=ctoken)
        if check(status == 204 and seen.get("status") == "paid", f"paid (fake Bakong) -> {seen.get('status')}"):
            status, sale = call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [line(para, "strip", 2)],
                                "payments": [{"method": "KHQR", "currency": "USD", "amount": str(price),
                                              "khqr_id": qr["id"]}]}, token=ctoken, headers=key())  # fmt: skip
            _, seen = call("GET", f"{sales}/payments/khqr/{qr['id']}", token=ctoken)
            check(status == 201 and seen.get("status") == "used",
                  f"sale {sale.get('number')} paid by KHQR; the QR is used ({seen.get('status')})")  # fmt: skip

        # 3. supplier return: the credit lowers what we owe
        _, before = call("GET", f"{pur}/suppliers/{supplier['id']}/balance", token=token)
        status, ret = call("POST", f"{pur}/supplier-returns", {"branch_id": bid, "supplier_id": supplier["id"],
                           "reason": "damaged", "lines": [{"batch_id": batch, "medicine_id": para["id"],
                                                           "qty_base": 20}]}, token=token)  # fmt: skip
        status, ret = call("POST", f"{pur}/supplier-returns/{ret.get('id')}/submit", {"settle": "credit"},
                           token=token, headers=key())  # fmt: skip
        _, after = call("GET", f"{pur}/suppliers/{supplier['id']}/balance", token=token)
        check(status == 200 and ret.get("status") == "credited"
              and Decimal(before.get("owed", "0")) - Decimal(after.get("owed", "0")) == Decimal(ret.get("total", "-1")),
              f"return {ret.get('number')} of 20 tablets: owed {before.get('owed')} -> {after.get('owed')}")  # fmt: skip
        body = json.dumps({"type": "supplier_return", "supplier_return_id": ret.get("id"), "lang": "en"}).encode()

        def return_pdf():
            st, pdf, _ = call_raw("POST", docs, body, token, {"Content-Type": "application/json"})
            return pdf if st == 200 else None

        pdf = wait_for(return_pdf, tries=20)
        check(bool(pdf) and pdf.startswith(b"%PDF"), "the return note PDF for the supplier")

        # 4. recall: the lot cannot be sold any more
        status, recall = call("POST", f"{inv}/recalls", {"medicine_id": para["id"], "lot_nos": ["S8BLOT"],
                              "reason": "Smoke test recall"}, token=token, headers=key())  # fmt: skip
        check(status == 201, f"owner recalls lot S8BLOT -> {recall.get('number')}")
        status, p = preview([line(para, "strip", 1)])
        status, r = call("POST", f"{sales}/invoices", {"branch_id": bid, "lines": [line(para, "strip", 1)],
                         "payments": [{"method": "cash", "amount": "5.00"}]}, token=ctoken, headers=key())  # fmt: skip
        check(r.get("code") == "OUT_OF_STOCK" and "OUT_OF_STOCK" in codes(p),
              f"the recalled lot is not sold: sale -> {r.get('code')}, preview -> {codes(p)}")  # fmt: skip
        _, detail = call("GET", f"{inv}/recalls/{recall.get('id')}", token=token)
        print(f"        recall {detail.get('number')}: " + ", ".join(
            f"{x['lot_no']} on hand {x['on_hand']} ({x['action']})" for x in detail.get("lines", [])))

        # 5. customer statement PDF in Khmer and English
        status, customer = call("POST", f"{cust}/customers", {"phone": f"096{random.randint(1000000, 9999999)}",
                                "name": "Smoke statement customer"}, token=token)  # fmt: skip
        for lang in ("km", "en"):
            body = json.dumps({"type": "customer_statement", "customer_id": customer.get("id"), "lang": lang}).encode()
            st, pdf, _ = call_raw("POST", docs, body, token, {"Content-Type": "application/json"})
            if check(st == 200 and pdf.startswith(b"%PDF"), f"customer statement PDF ({lang})"):
                out = Path(tempfile.gettempdir()) / f"pharmacy-smoke-statement-{lang}.pdf"
                out.write_bytes(pdf)
                print(f"        open {out}")

        # 6. 2FA backup code, then the session it opened is revoked
        status, fresh = call("POST", "/api/auth/v1/2fa/backup-codes", {"password": OWNER_LOGIN["password"]},
                             token=token)  # fmt: skip
        codes_ = fresh.get("codes") or []
        check(status == 200 and len(codes_) == 10, f"10 new backup codes ({status})")
        _, step1 = call("POST", "/api/auth/v1/login", {"phone": OWNER_LOGIN["phone"], "password": OWNER_LOGIN["password"]})
        status, step2 = call("POST", "/api/auth/v1/login/2fa", {"mfa_token": step1.get("mfa_token", ""),
                             "backup_code": codes_[0] if codes_ else "x" * 11})  # fmt: skip
        other = step2.get("access_token", "")
        check(status == 200 and bool(other), f"owner logs in with a backup code -> {status}")
        _, rows = call("GET", "/api/auth/v1/me/sessions", token=token)
        mine = [r for r in rows if r.get("current")] if isinstance(rows, list) else []
        check(len(rows) >= 2 and len(mine) == 1, f"sessions listed ({len(rows)}), this one marked current")
        _, theirs = call("GET", "/api/auth/v1/me/sessions", token=other)
        sid = next((r["id"] for r in theirs if r.get("current")), None) if isinstance(theirs, list) else None
        status, _ = call("POST", f"/api/auth/v1/me/sessions/{sid}/revoke", token=token)
        st, _ = call("GET", "/api/sales/v1/whoami", token=other)
        check(status == 204 and st == 401, f"that session revoked: its token -> {st}")

        for action in ("recall.started", "supplier_return.submitted", "khqr.created", "user.backup_code_used",
                       "user.session_revoked"):  # fmt: skip

            def logged(action=action):
                _, log = call("GET", f"/api/auth/v1/audit-logs?action={action}&size=1", token=token)
                return log.get("total")

            check(bool(wait_for(logged)), f"User Log shows {action}")
    finally:
        if recall.get("id"):
            call("POST", f"{inv}/recalls/{recall['id']}/lift", {"reason": "smoke test clean-up"}, token=token)
        if customer.get("id"):
            call("POST", f"{cust}/customers/{customer['id']}/deactivate", {"reason": "smoke test"}, token=token)
        if supplier.get("id"):
            call("POST", f"{pur}/suppliers/{supplier['id']}/deactivate", {"reason": "smoke test"}, token=token)
        remove_test_cashier(token, bid, cashier)


def main() -> int:
    print(f"Smoke test against {BASE}\n")
    tokens = s0_checks()
    if tokens is None:
        return summary()
    run_s1 = os.environ.get("SMOKE_S1") or input(
        "\nAlso run the S1 checks? It creates a test branch and cashier, then deactivates them. [y/N] "
    )
    if run_s1.strip().lower() in ("y", "yes", "1"):
        print()
        s1_checks(tokens["access_token"])
    run_s1b = os.environ.get("SMOKE_S1B") or input(
        "\nAlso run the S1b checks? It imports the 20 sample products (they stay), searches, prints\n"
        "labels, and creates then deactivates a test branch and cashier. [y/N] "
    )
    if run_s1b.strip().lower() in ("y", "yes", "1"):
        print()
        s1b_checks(tokens["access_token"])
    run_s2 = os.environ.get("SMOKE_S2") or input(
        "\nAlso run the S2 checks? It creates a test branch, supplier and PO, receives and pays it\n"
        "(stock stays in the deactivated test branch). [y/N] "
    )
    if run_s2.strip().lower() in ("y", "yes", "1"):
        print()
        s2_checks(tokens["access_token"])
    run_s3 = os.environ.get("SMOKE_S3") or input(
        "\nAlso run the S3 checks? It creates a test branch, stock, sales, a customer, a cancel and a return\n"
        "(all in the deactivated test branch). [y/N] "
    )
    if run_s3.strip().lower() in ("y", "yes", "1"):
        print()
        s3_checks(tokens["access_token"])
    run_s4 = os.environ.get("SMOKE_S4") or input(
        "\nAlso run the S4 checks? It creates a test branch, pharmacist, patient, doctor, an Rx with an image\n"
        "and a sale on it (all deactivated afterwards). [y/N] "
    )
    if run_s4.strip().lower() in ("y", "yes", "1"):
        print()
        s4_checks(tokens["access_token"])
    run_s5 = os.environ.get("SMOKE_S5") or input(
        "\nAlso run the S5 checks? It creates a test branch, two pharmacists with PINs, stock-in, a controlled sale,\n"
        "a destruction and a stock take of DIAZ5 (all in the deactivated test branch). [y/N] "
    )
    if run_s5.strip().lower() in ("y", "yes", "1"):
        print()
        s5_checks(tokens["access_token"])
    run_s6 = os.environ.get("SMOKE_S6") or input(
        "\nAlso run the S6 checks? It creates two test branches, a transfer with a short receipt, a purchase\n"
        "request turned into a PO group, and a re-order list (all deactivated afterwards). [y/N] "
    )
    if run_s6.strip().lower() in ("y", "yes", "1"):
        print()
        s6_checks(tokens["access_token"])
    run_s7 = os.environ.get("SMOKE_S7") or input(
        "\nAlso run the S7 checks? It creates a test branch, a promotion and a hamper (deactivated afterwards),\n"
        "a suspended cart, a sale order with a deposit and a commission rule. [y/N] "
    )
    if run_s7.strip().lower() in ("y", "yes", "1"):
        print()
        s7_checks(tokens["access_token"])
    run_s8 = os.environ.get("SMOKE_S8") or input(
        "\nAlso run the S8 checks? It creates a test branch with two sales and a return, exports reports and\n"
        "queues the daily Telegram summary (sent only with TELEGRAM_BOT_TOKEN). [y/N] "
    )
    if run_s8.strip().lower() in ("y", "yes", "1"):
        print()
        s8_checks(tokens["access_token"])
    run_s8b = os.environ.get("SMOKE_S8B") or input(
        "\nAlso run the S8b checks? It creates a test branch, a supplier, a PO, a KHQR sale (fake Bakong: development\n"
        "only), a supplier return, a recall (lifted afterwards), a customer statement, a backup-code login. [y/N] "
    )
    if run_s8b.strip().lower() in ("y", "yes", "1"):
        print()
        s8b_checks(tokens["access_token"])

    status, _ = call(
        "POST",
        "/api/auth/v1/logout",
        {"refresh_token": tokens["refresh_token"]},
        token=tokens["access_token"],
    )
    check(status == 204, f"logout -> 204 (got {status})")
    status, _ = call("GET", "/api/sales/v1/whoami", token=tokens["access_token"])
    check(status == 401, f"same token after logout -> 401 (got {status})")
    return summary()


def summary() -> int:
    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
