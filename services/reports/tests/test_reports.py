"""Reports from events: day boundary in Phnom Penh, cancels and returns (choice K),
KHR per invoice rate, branch scoping, cost never shown or exported without the
permission, duplicate / older events ignored, the reports themselves."""

import csv
import io
from uuid import uuid4

from openpyxl import load_workbook

from reports_service.api.reports import get_document
from reports_service.main import app

from .conftest import INTERNAL, MANAGER, PP1, PP2, event, get, invoice, line, product, user

CASHIER = user("cashier", "dashboard.view,reports.sales")


async def test_midnight_in_phnom_penh_splits_the_days(client) -> None:
    para = await product()
    await event("invoice.created", invoice("PP1-INV-1", [line(para, 10, "1.00", "0.40")], at="2026-10-26T16:59:59+00:00"))
    await event("invoice.created", invoice("PP1-INV-2", [line(para, 20, "2.00", "0.80")], at="2026-10-26T17:00:00+00:00"))
    r = await get(client, "sales/summary", by="day", date_from="2026-10-25", date_to="2026-10-27")
    assert [(x["key"], x["net"]) for x in r.json()["rows"]] == [("2026-10-26", "1.00"), ("2026-10-27", "2.00")]


async def test_cancel_leaves_its_day_return_counts_on_its_own_day(client) -> None:
    para, inv_id = await product(), uuid4()
    lid = uuid4()
    lines = [line(para, 10, "1.00", "0.40", line_id=lid)]
    sold = invoice("PP1-INV-1", lines, at="2026-10-26T03:00:00+00:00", invoice_id=inv_id)
    await event("invoice.created", sold)
    other = invoice("PP1-INV-2", [line(para, 30, "3.00", "1.20")], at="2026-10-26T04:00:00+00:00")
    await event("invoice.created", other)
    ret = {"return_id": str(uuid4()), "number": "PP1-RT-1", "refund_method": "cash", "refund_usd": "1.50",
           "to_quarantine": False, "reason": "x", "created_at": "2026-10-27T02:00:00+00:00",
           "lines": [{"line_id": other["lines"][0]["line_id"], "batch_id": str(uuid4()), "qty_base": 15, "amount": "1.50"}]}  # fmt: skip
    await event("invoice.returned", {**other, "version": 2, "returns": [ret]})
    await event("invoice.cancelled", {**sold, "version": 2, "status": "cancelled",
                                      "cancelled_at": "2026-10-27T03:00:00+00:00"})  # fmt: skip
    dash = (await get(client, "dashboard")).json()
    assert dash["yesterday"]["sales"] == "3.00" and dash["yesterday"]["invoices"] == 1  # the cancelled one left
    assert dash["today"]["returns"] == "1.50" and dash["today"]["net_sales"] == "-1.50"
    assert dash["today"]["gross_profit"] == "-0.90"  # 1.50 back, its cost 0.60 back
    profit = (await get(client, "sales/profit", date_from="2026-10-26", date_to="2026-10-27")).json()
    assert [(x["day"], x["revenue"], x["profit"]) for x in profit["rows"]] == [
        ("2026-10-26", "3.00", "1.80"), ("2026-10-27", "-1.50", "-0.90")]
    cancels = (await get(client, "sales/cancellations", date_from="2026-10-27", date_to="2026-10-27")).json()
    assert [x["invoice"] for x in cancels["rows"]] == ["PP1-INV-1"]
    pays = (await get(client, "payments", date_from="2026-10-26", date_to="2026-10-27")).json()
    assert pays["summary"] == {"cash": "1.50"}  # 1.00 + 3.00 in, 1.00 back (cancel), 1.50 refunded


async def test_khr_uses_each_invoices_own_rate(client) -> None:
    para = await product()
    await event("invoice.created", invoice("A", [line(para, 10, "1.00", "0.40")], rate=4000))
    await event("invoice.created", invoice("B", [line(para, 10, "1.00", "0.40")], rate=4150))
    dash = (await get(client, "dashboard")).json()
    assert dash["today"]["sales_khr"] == 4000 + 4200  # each rounded to 100 riel at its own rate


async def test_duplicate_and_older_events_change_nothing(client) -> None:
    para, mid = await product(), uuid4()
    v2 = invoice("A", [line(para, 10, "1.00", "0.40")], version=2)
    assert await event("invoice.created", v2, mid)
    assert not await event("invoice.created", v2, mid)  # same message
    await event("invoice.created", {**v2, "version": 1, "lines": [line(para, 99, "9.90", "1.00")]})  # older
    detail = (await get(client, "sales/detail")).json()
    assert detail["total"] == 1 and detail["summary"]["net"] == "1.00"


async def test_branch_scope_and_cost_never_leaks(client, monkeypatch) -> None:
    para = await product()
    await event("invoice.created", invoice("PP1-INV-1", [line(para, 10, "1.00", "0.40")]))
    await event("invoice.created", invoice("PP2-INV-1", [line(para, 10, "5.00", "2.00")], branch=PP2))
    mine = (await get(client, "sales/detail", MANAGER)).json()
    assert [x["invoice"] for x in mine["rows"]] == ["PP1-INV-1"]
    assert (await get(client, "sales/detail", MANAGER, branch_id=PP2)).json()["code"] == "BRANCH_FORBIDDEN"
    assert len((await get(client, "sales/detail")).json()["rows"]) == 2  # the owner sees every branch
    seen = (await get(client, "sales/detail", CASHIER)).json()
    assert {"cost", "profit"} & {c["key"] for c in seen["columns"]} == set()
    assert "cost" not in seen["rows"][0] and "cost" not in seen["summary"]
    dash = (await get(client, "dashboard", CASHIER)).json()
    assert "gross_profit" not in dash["today"]
    assert (await get(client, "sales/margin-by-item", CASHIER)).status_code == 403
    out = await get(client, "sales/detail", CASHIER, format="csv")
    header = next(csv.reader(io.StringIO(out.content.decode("utf-8-sig"))))
    assert out.status_code == 200 and "Cost" not in header and "Profit" not in header and "Net" in header
    out = await get(client, "sales/detail", CASHIER, format="xlsx")
    sheet = load_workbook(io.BytesIO(out.content)).active
    assert "Cost" not in [c.value for c in sheet[1]]
    sent = {}

    class Document:
        async def post(self, path: str, body: dict) -> dict:
            sent.update(body)
            return {"pdf_base64": "JVBERi0="}

    app.dependency_overrides[get_document] = lambda: Document()
    try:
        out = await get(client, "sales/detail", CASHIER, format="pdf")
    finally:
        app.dependency_overrides.clear()
    assert out.content.startswith(b"%PDF") and "Cost" not in [c["label"] for c in sent["columns"]]
    owner = await get(client, "sales/detail", format="csv")
    assert "Cost" in next(csv.reader(io.StringIO(owner.content.decode("utf-8-sig"))))


async def test_exports_are_limited_per_minute(client) -> None:
    for _ in range(10):
        assert (await get(client, "sales/detail", CASHIER | {"X-User-Id": CASHIER["X-User-Id"]}, format="csv")
                ).status_code == 200  # fmt: skip
    r = await get(client, "sales/detail", CASHIER, format="csv")
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"


async def test_stock_expiry_and_slow_moving(client) -> None:
    para, ors = await product("PARA500"), await product("ORS")
    for med, batch, expiry, qty, seq in ((para, uuid4(), "2026-11-20", 100, 1), (ors, uuid4(), "2026-09-30", 40, 2)):
        await event("stock.changed", {"movement_id": str(uuid4()), "seq": seq, "branch_id": str(PP1),
                                      "batch_id": str(batch), "medicine_id": str(med), "type": "in", "delta": qty,
                                      "qty_after": qty, "lot_no": f"L{seq}", "expiry_date": expiry,
                                      "cost_per_base": "0.0500", "occurred_at": "2026-06-01T03:00:00+00:00"})  # fmt: skip
    await event("invoice.created", invoice("A", [line(para, 10, "1.00", "0.50")], at="2026-10-20T03:00:00+00:00"))
    stock = (await get(client, "stock")).json()
    assert stock["summary"] == {"qty_on_hand": 140, "value": "7.00"}
    soon = (await get(client, "expiry", within=30)).json()
    assert [(x["sku"], x["days_left"]) for x in soon["rows"]] == [("PARA500", 24)]
    expired = (await get(client, "expiry", status="expired")).json()
    assert [x["sku"] for x in expired["rows"]] == ["ORS"]
    slow = (await get(client, "stock/slow-moving", days=5)).json()
    assert sorted((x["sku"], x["last_sale"]) for x in slow["rows"]) == [("ORS", None), ("PARA500", "2026-10-20")]
    assert [x["sku"] for x in (await get(client, "stock/slow-moving", days=30)).json()["rows"]] == ["ORS"]
    blind = (await get(client, "stock", user("cashier", "reports.stock"))).json()
    assert blind["summary"] == {"qty_on_hand": 140} and "value" not in blind["rows"][0]


async def test_abc_classes(client) -> None:
    meds = [await product(f"M{i}") for i in range(4)]
    for med, net in zip(meds, ("80.00", "15.00", "4.00", "1.00"), strict=True):
        await event("invoice.created", invoice(f"I{net}", [line(med, 1, net, "0.10", sku=f"S{net}")]))
    rows = (await get(client, "stock/abc")).json()["rows"]
    assert [(x["class"], x["net"]) for x in rows] == [("A", "80.00"), ("B", "15.00"), ("C", "4.00"), ("C", "1.00")]


async def test_payables_and_receivables_aging(client) -> None:
    supplier = uuid4()
    await event("supplier.created", {"supplier_id": str(supplier), "code": "S", "name": "DKSH", "payment_terms_days": 30})
    for n, due in (("G1", "2026-10-30"), ("G2", "2026-09-10"), ("G3", "2026-07-01")):
        await event("goods.received", {"receipt_id": str(uuid4()), "number": n, "branch_id": str(PP1),
                                       "supplier_id": str(supplier), "received_at": "2026-06-01T03:00:00+00:00",
                                       "total": "100.00", "due_on": due, "lines": []})  # fmt: skip
    rows = (await get(client, "payables/aging", MANAGER)).json()["rows"]
    assert rows[0]["not_due"] == "100.00" and rows[0]["d31_60"] == "100.00" and rows[0]["d90_plus"] == "100.00"
    assert (await get(client, "payables/aging", user("branch_manager", "reports.purchases"))).status_code == 403
    customer, inv_id = uuid4(), uuid4()
    await event("customer.created", {"customer_id": str(customer), "name": "Clinic", "group_id": None})
    await event("invoice.created", invoice("PP1-INV-9", [line(await product(), 10, "20.00", "1.00")], invoice_id=inv_id,
                                           customer=customer, at="2026-08-01T03:00:00+00:00"))  # fmt: skip
    await event("credit.charged", {"customer_id": str(customer), "invoice_id": str(inv_id), "branch_id": str(PP1),
                                   "amount": "20.00", "occurred_at": "2026-08-01T03:00:00+00:00"})  # fmt: skip
    await event("customer_payment.created", {"payment_id": str(uuid4()), "number": "P1", "customer_id": str(customer),
                                             "branch_id": str(PP1), "method": "cash", "amount": "5.00",
                                             "status": "posted", "paid_on": "2026-10-01",
                                             "allocations": [{"invoice_no": "PP1-INV-9", "amount": "5.00",
                                                              "reversed": False}]})  # fmt: skip
    owner_rows = (await get(client, "receivables/aging")).json()["rows"]
    assert [(x["party"], x["d61_90"], x["total"]) for x in owner_rows] == [("Clinic", "15.00", "15.00")]


async def test_cost_change_from_receipts(client) -> None:
    para, supplier = await product(), uuid4()
    for n, cost, when in (("G1", "0.0400", "2026-09-01"), ("G2", "0.0500", "2026-10-01"), ("G3", "0.0500", "2026-10-20")):
        await event("goods.received", {"receipt_id": str(uuid4()), "number": n, "branch_id": str(PP1),
                                       "supplier_id": str(supplier), "received_at": f"{when}T03:00:00+00:00",
                                       "lines": [{"receipt_line_id": str(uuid4()), "medicine_id": str(para),
                                                  "qty_base": 100, "lot_no": n, "expiry_date": "2028-01-31",
                                                  "cost_per_base": cost}]})  # fmt: skip
    rows = (await get(client, "purchases/cost-changes", MANAGER, date_from="2026-09-01")).json()["rows"]
    assert [(x["receipt"], x["previous"], x["change"], x["change_pct"]) for x in rows] == [
        ("G1", None, None, None), ("G2", "0.0400", "0.0100", "25.00"), ("G3", "0.0500", "0.0000", "0.00")]
    changed = (await get(client, "purchases/cost-changes", MANAGER, date_from="2026-09-01", changed_only=True)).json()
    assert [x["receipt"] for x in changed["rows"]] == ["G2"]
    hidden = (await get(client, "purchases/cost-changes", user("pharmacist", "reports.purchases"))).json()
    assert "cost_per_base" not in hidden["rows"][0] and "change" not in hidden["rows"][0]


async def test_modifications_from_the_user_log(client) -> None:
    await event("audit.recorded", {"service": "catalog", "action": "medicine.updated", "entity_type": "medicine",
                                   "entity_id": "m1", "actor_id": None, "before": {"pack_units.box.sell_price": "8.00"},
                                   "after": {"pack_units.box.sell_price": "8.50"}})  # fmt: skip
    await event("audit.recorded", {"service": "auth", "action": "user.created", "entity_type": "user"})  # not catalog
    rows = (await get(client, "modifications", MANAGER)).json()["rows"]
    assert [(x["field"], x["old"], x["new"]) for x in rows] == [("pack_units.box.sell_price", "8.00", "8.50")]


async def test_rx_report_needs_prescriptions_view_and_has_no_patient(client) -> None:
    para = await product()
    rx = {"prescription_number": "PP1-RX-1", "doctor_name": "Dr Sok", "patient_name_en": "Secret Patient",
          "is_controlled": False}  # fmt: skip
    await event("invoice.created", invoice("A", [line(para, 10, "1.00", "0.40", rx=rx, rx_item_id=str(uuid4()))]))
    assert (await get(client, "rx/dispensing", MANAGER)).status_code == 403
    r = await get(client, "rx/dispensing", user("pharmacist", "reports.sales,prescriptions.view"))
    assert [x["rx_number"] for x in r.json()["rows"]] == ["PP1-RX-1"] and "Secret Patient" not in r.text


async def test_internal_daily_summary_needs_the_service_token(client) -> None:
    assert (await client.get("/internal/v1/daily-summary")).status_code == 401
    para = await product()
    await event("invoice.created", invoice("A", [line(para, 10, "1.00", "0.40")]))
    out = (await client.get("/internal/v1/daily-summary", headers=INTERNAL, params={"profit": "true"})).json()
    assert out["today"]["sales"] == "1.00" and out["today"]["gross_profit"] == "0.60"
    assert {b["code"] for b in out["branches"]} == {"PP1", "PP2"} and "top_debtors" not in out
    assert (await client.get("/internal/v1/outbox", headers=INTERNAL)).status_code == 403  # not for notification
