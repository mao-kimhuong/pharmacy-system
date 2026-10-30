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
last unit at once, Rx-only / controlled refused, a credit sale over the limit
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

Without prompts: SMOKE_PHONE, SMOKE_PASSWORD, SMOKE_S1=y, SMOKE_S1B=y, SMOKE_S2=y, SMOKE_S3=y, SMOKE_S4=y.

Uses only the Python standard library.
"""

import getpass
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


def owner_login() -> dict | None:
    phone = os.environ.get("SMOKE_PHONE") or input("Owner phone: ")
    password = os.environ.get("SMOKE_PASSWORD") or getpass.getpass("Owner password: ")
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
    check(status == 422 and r.get("code") == "CONTROLLED_NOT_AVAILABLE",
          f"controlled refused -> CONTROLLED_NOT_AVAILABLE ({r.get('code')})")  # fmt: skip

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
