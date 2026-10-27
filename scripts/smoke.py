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

Without prompts: SMOKE_PHONE, SMOKE_PASSWORD, SMOKE_S1=y, SMOKE_S1B=y, SMOKE_S2=y.

Uses only the Python standard library.
"""

import getpass
import json
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, timedelta
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
