"""Events the reports service listens to (queue `reports.events`) and the read
models they fill. The same handlers run for live events and for the backfill
(outbox replay, services/backfill.py), so every handler is an idempotent upsert
keyed by the source id; versioned snapshots (invoice, transfer, count) ignore
older or equal versions.

Days are Asia/Phnom_Penh calendar days. A sale belongs to the day it was
completed; a cancel takes it out of that day (status cancelled); a return counts
on the day it was made (choice K). KHR uses each invoice's own rate.
"""

import contextvars
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock, copies
from pharmacy_shared.copies import BRANCH_EVENTS, MEDICINE_EVENTS

from ..models import (
    Alert,
    Bill,
    BillAllocation,
    CommissionLine,
    CommissionPeriod,
    Count,
    CountLine,
    Customer,
    Debt,
    DebtAllocation,
    DebtReversal,
    Invoice,
    InvoiceLine,
    KnownBranch,
    Lookup,
    Modification,
    Movement,
    Payment,
    PendingRequest,
    Product,
    ProductPackUnit,
    ReceiptLine,
    RegisterIssue,
    ReturnLine,
    SalesDaily,
    Shrinkage,
    Staff,
    StockRow,
    Supplier,
    Transfer,
)

ROUTING_KEYS = (
    "medicine.*", "category.*", "brand.*", "promotion.*", "branch.*", "user.*", "supplier.*", "customer.*",
    "invoice.*", "stock.changed", "stock.low", "batch.expiring", "goods.received", "supplier_payment.*",
    "customer_payment.*", "credit.*", "deposit.*", "transfer.*", "transfer_request.*", "purchase_request.*",
    "shrinkage.*", "count.*", "register.*", "commission.*", "commission_period.*", "audit.recorded",
)  # fmt: skip

NOBODY = UUID(int=0)  # sales_daily key for a sale without a known staff member
SOLD = ("completed",)
MONEY_METHODS = ("cash", "card", "ABA", "KHQR")  # credit and deposit are not money taken at the till
MODIFIED = ("medicine", "pack_unit", "promotion", "hamper", "category", "brand")

# The outbox created_at of the event being replayed (backfill), for payloads
# written before they carried their own time. Live events: now.
event_time: contextvars.ContextVar[datetime | None] = contextvars.ContextVar("event_time", default=None)


def when(value: str | None) -> datetime:
    if value:
        return datetime.fromisoformat(value)
    return event_time.get() or clock.now()


def local_day(at: datetime) -> date:
    return at.astimezone(clock.TIMEZONE).date()


def D(value: Any) -> Decimal:  # noqa: N802
    return Decimal(str(value)) if value not in (None, "") else Decimal("0")


def U(value: Any) -> UUID | None:  # noqa: N802
    return UUID(str(value)) if value else None


async def _upsert(session: AsyncSession, model: type, values: dict[str, Any], keys: list[str],
                  where: Any = None) -> None:  # fmt: skip
    stmt = insert(model).values(**values)
    stmt = stmt.on_conflict_do_update(index_elements=keys, set_={k: v for k, v in values.items() if k not in keys},
                                      where=where)  # fmt: skip
    await session.execute(stmt)


async def _insert_once(session: AsyncSession, model: type, values: dict[str, Any]) -> bool:
    result = await session.execute(insert(model).values(**values).on_conflict_do_nothing())
    return bool(result.rowcount)


# ---------------------------------------------------------------- dispatch


async def handle_event(session: AsyncSession, event_type: str, payload: dict[str, Any], message_id: UUID) -> None:
    kind = event_type.split(".")[0]
    if event_type in MEDICINE_EVENTS:
        await copies.upsert_product(session, Product, ProductPackUnit, payload)
    elif kind in ("category", "brand") and payload.get("id"):
        await _upsert(session, Lookup, {"id": UUID(str(payload["id"])), "kind": kind,
                                        "name_en": payload.get("name_en") or "", "name_km": payload.get("name_km") or ""},
                      ["id"])  # fmt: skip
    elif kind == "promotion" and payload.get("promotion_id"):
        await _upsert(session, Lookup, {"id": UUID(payload["promotion_id"]), "kind": "promotion",
                                        "name_en": f"{payload.get('code')} {payload.get('name') or ''}".strip()[:160],
                                        "name_km": (payload.get("name_km") or "")[:160]}, ["id"])  # fmt: skip
    elif event_type in BRANCH_EVENTS:
        await copies.upsert_branch(session, KnownBranch, payload)
    elif event_type == "branch.settings_updated":
        if payload.get("expiry_alert_days") is not None:
            await session.execute(update(KnownBranch).where(KnownBranch.id == UUID(str(payload["branch_id"])))
                                  .values(expiry_alert_days=[int(d) for d in payload["expiry_alert_days"]]))  # fmt: skip
    elif kind == "user" and payload.get("name") is not None:
        await _upsert(session, Staff, {"id": UUID(payload["user_id"]), "name": payload["name"],
                                       "role": payload.get("role") or ""}, ["id"])  # fmt: skip
    elif kind == "supplier" and payload.get("supplier_id"):
        await _upsert(session, Supplier, {"id": UUID(payload["supplier_id"]), "code": payload.get("code") or "",
                                          "name": payload["name"],
                                          "payment_terms_days": int(payload.get("payment_terms_days") or 0)},
                      ["id"])  # fmt: skip
    elif kind == "customer" and payload.get("customer_id"):
        await _upsert(session, Customer, {"id": UUID(payload["customer_id"]), "name": payload["name"],
                                          "group_id": U(payload.get("group_id"))}, ["id"])  # fmt: skip
    elif kind == "invoice":
        await invoice(session, payload)
    elif event_type == "stock.changed":
        await movement(session, payload)
    elif event_type in ("stock.low", "batch.expiring"):
        await alert(session, event_type, payload)
    elif event_type == "goods.received":
        await goods_received(session, payload)
    elif kind == "supplier_payment":
        await supplier_payment(session, payload)
    elif kind == "customer_payment":
        await customer_payment(session, payload)
    elif event_type == "credit.charged":
        await credit_charged(session, payload)
    elif event_type == "credit.reversed":
        await credit_reversed(session, payload)
    elif kind == "deposit":
        await deposit(session, payload)
    elif kind == "transfer":
        await transfer(session, payload)
    elif kind in ("transfer_request", "purchase_request"):
        await request(session, kind, payload)
    elif kind == "shrinkage":
        await shrinkage(session, payload)
    elif kind == "count":
        await count(session, event_type, payload)
    elif kind == "register":
        await register(session, event_type, payload)
    elif event_type == "commission.recorded":
        await commission_line(session, payload)
    elif kind == "commission_period":
        await _upsert(session, CommissionPeriod, {"id": UUID(payload["period_id"]),
                                                  "branch_id": UUID(payload["branch_id"]),
                                                  "month": date.fromisoformat(payload["month"]),
                                                  "status": payload["status"]}, ["id"])  # fmt: skip
    elif event_type == "audit.recorded":
        await modification(session, payload, message_id)


# ---------------------------------------------------------------- sales


async def rebuild_day(session: AsyncSession, branch_id: UUID, day: date) -> None:
    """sales_daily for one branch and day, from its completed invoice lines."""
    await session.execute(delete(SalesDaily).where(SalesDaily.branch_id == branch_id, SalesDaily.day == day))
    x = InvoiceLine
    staff = func.coalesce(x.staff_id, NOBODY)
    rows = select(
        x.branch_id, x.sale_date, x.medicine_id, staff, func.sum(x.qty_base), func.sum(x.line_total), func.sum(x.promo_discount + x.manual_discount),
        func.sum(x.net), func.sum(x.net_khr), func.sum(x.cost), func.count(),
    ).where(x.branch_id == branch_id, x.sale_date == day, x.status.in_(SOLD)).group_by(
        x.branch_id, x.sale_date, x.medicine_id, staff)  # fmt: skip
    await session.execute(insert(SalesDaily).from_select(
        ["branch_id", "day", "medicine_id", "staff_id", "qty_base", "gross", "discount", "net",
         "net_khr", "cost", "lines"], rows))  # fmt: skip


def _khr(usd: Decimal, rate: int | None) -> int:
    return int((usd * (rate or 0)).quantize(Decimal("1"))) if rate else 0


async def invoice(session: AsyncSession, p: dict[str, Any]) -> None:
    if not p.get("number") or not p.get("completed_at"):
        return  # failed or pending sales never had a number: nothing to report
    inv_id, version = UUID(p["invoice_id"]), int(p["version"])
    old = await session.get(Invoice, inv_id)
    if old is not None and old.version >= version:
        return
    branch_id = UUID(p["branch"]["id"])
    completed = datetime.fromisoformat(p["completed_at"])
    cancelled = datetime.fromisoformat(p["cancelled_at"]) if p.get("cancelled_at") else None
    rate = p.get("khr_per_usd")
    cashier = U(p.get("cashier_id"))
    customer = U((p.get("customer") or {}).get("id"))
    sale_date = local_day(completed)
    lines = p.get("lines") or []
    await _upsert(session, Invoice, {
        "id": inv_id, "version": version, "number": p["number"], "branch_id": branch_id, "status": p["status"],
        "cashier_id": cashier, "customer_id": customer, "completed_at": completed, "sale_date": sale_date,
        "cancelled_at": cancelled, "cancel_date": local_day(cancelled) if cancelled else None,
        "cancel_reason": p.get("cancel_reason"), "subtotal": D(p.get("subtotal")), "discount": D(p.get("discount")),
        "total": D(p.get("total")), "cost": sum((D(x.get("cost")) for x in lines), Decimal("0")),
        "khr_per_usd": rate, "total_khr": p.get("total_khr"), "credit_amount": D(p.get("credit_amount")),
        "returned_total": D(p.get("returned_total")),
    }, ["id"])  # fmt: skip
    await session.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == inv_id))
    products = {pr.id: pr for pr in (await session.execute(select(Product).where(
        Product.id.in_([UUID(x["medicine_id"]) for x in lines])))).scalars()} if lines else {}  # fmt: skip
    by_id: dict[str, dict[str, Any]] = {}
    for x in lines:
        product = products.get(UUID(x["medicine_id"]))
        rx = x.get("rx") or {}
        net = D(x.get("net", x.get("line_total")))
        by_id[x["line_id"]] = x
        session.add(InvoiceLine(
            id=UUID(x["line_id"]), invoice_id=inv_id, branch_id=branch_id, sale_date=sale_date, status=p["status"],
            staff_id=U(x.get("staff_id")) or cashier, customer_id=customer, line_no=x["line_no"],
            medicine_id=UUID(x["medicine_id"]), category_id=product.category_id if product else None,
            brand_id=product.brand_id if product else None, sku=x["sku"], name=x["name"], pack_unit=x["pack_unit"],
            qty=x["qty"], qty_base=x["qty_base"], unit_price=D(x["unit_price"]), line_total=D(x["line_total"]),
            promo_discount=D(x.get("promo_discount")), manual_discount=D(x.get("manual_discount")), net=net,
            net_khr=_khr(net, rate), cost=D(x.get("cost")), promotion_ids=list(x.get("promotion_ids") or []),
            is_hamper=bool(x.get("is_hamper")), is_rx=bool(x.get("rx_item_id")),
            is_controlled=bool(rx.get("is_controlled")), rx_number=rx.get("prescription_number"),
            doctor_name=rx.get("doctor_name"), returned_qty_base=int(x.get("returned_qty_base") or 0),
        ))  # fmt: skip
    # money taken at the till, change given, and given back on a cancel
    for i, pay in enumerate(p.get("payments") or []):
        if pay["method"] not in MONEY_METHODS:
            continue
        values = {"branch_id": branch_id, "kind": "sale", "method": pay["method"], "currency": pay["currency"],
                  "reference": p["number"], "staff_id": cashier, "party": ""}  # fmt: skip
        await _upsert(session, Payment, {**values, "id": f"sale:{inv_id}:{i}", "day": sale_date, "occurred_at": completed,
                                         "amount": D(pay["amount"]), "amount_usd": D(pay["amount_usd"])}, ["id"])  # fmt: skip
        if cancelled:
            await _upsert(session, Payment, {**values, "id": f"cancel:{inv_id}:{i}", "kind": "invoice_cancel",
                                             "day": local_day(cancelled), "occurred_at": cancelled,
                                             "amount": -D(pay["amount"]), "amount_usd": -D(pay["amount_usd"])}, ["id"])  # fmt: skip
    change = D(p.get("change_usd"))
    if change > 0:
        values = {"branch_id": branch_id, "method": "cash", "currency": "USD", "reference": p["number"],
                  "staff_id": cashier, "party": ""}  # fmt: skip
        await _upsert(session, Payment, {**values, "id": f"change:{inv_id}", "kind": "change", "day": sale_date,
                                         "occurred_at": completed, "amount": -change, "amount_usd": -change}, ["id"])  # fmt: skip
        if cancelled:
            await _upsert(session, Payment, {**values, "id": f"cancel-change:{inv_id}", "kind": "invoice_cancel",
                                             "day": local_day(cancelled), "occurred_at": cancelled, "amount": change,
                                             "amount_usd": change}, ["id"])  # fmt: skip
    for r in p.get("returns") or []:
        at = when(r.get("created_at"))
        rid = UUID(r["return_id"])
        for rl in r.get("lines") or []:
            line = by_id.get(rl["line_id"], {})
            share = Decimal(rl["qty_base"]) / Decimal(line.get("qty_base") or rl["qty_base"])
            amount = D(rl.get("amount"))
            await _upsert(session, ReturnLine, {
                "id": f"{rid}:{rl['line_id']}:{rl.get('batch_id')}", "return_id": rid, "number": r.get("number"),
                "invoice_id": inv_id, "invoice_number": p["number"], "line_id": UUID(rl["line_id"]),
                "branch_id": branch_id, "return_date": local_day(at), "staff_id": cashier,
                "medicine_id": UUID(line["medicine_id"]) if line else NOBODY, "sku": line.get("sku", ""),
                "name": line.get("name", ""), "qty_base": rl["qty_base"], "amount": amount,
                "amount_khr": _khr(amount, rate), "cost": (D(line.get("cost")) * share).quantize(Decimal("0.01")),
                "refund_method": r.get("refund_method") or "", "reason": r.get("reason") or "",
                "to_quarantine": bool(r.get("to_quarantine")),
            }, ["id"])  # fmt: skip
        if r.get("refund_method") in MONEY_METHODS:
            refund = D(r.get("refund_usd"))
            await _upsert(session, Payment, {"id": f"refund:{rid}", "branch_id": branch_id, "day": local_day(at),
                                             "occurred_at": at, "kind": "refund", "method": r["refund_method"],
                                             "currency": "USD", "amount": -refund, "amount_usd": -refund,
                                             "reference": r.get("number") or p["number"], "staff_id": cashier,
                                             "party": ""}, ["id"])  # fmt: skip
    await session.flush()
    days = {(branch_id, sale_date)}
    if old is not None and old.sale_date:
        days.add((old.branch_id, old.sale_date))
    for b, d in days:
        await rebuild_day(session, b, d)


# ---------------------------------------------------------------- stock


async def movement(session: AsyncSession, p: dict[str, Any]) -> None:
    if not p.get("batch_id") or not p.get("branch_id"):
        return
    at = when(p.get("occurred_at"))
    meta = p.get("meta") or {}
    values = {
        "id": UUID(p["movement_id"]), "seq": int(p["seq"]), "branch_id": UUID(p["branch_id"]),
        "batch_id": UUID(p["batch_id"]), "medicine_id": UUID(p["medicine_id"]), "type": p["type"],
        "delta": int(p["delta"]), "qty_after": int(p["qty_after"]), "lot_no": p["lot_no"],
        "expiry_date": date.fromisoformat(p["expiry_date"]), "cost_per_base": D(p["cost_per_base"]),
        "reason": (p.get("reason") or "")[:255], "reason_code": str(meta.get("reason") or "")[:20],
        "ref_type": p.get("ref_type") or "", "ref_id": str(p.get("ref_id") or "")[:80],
        "is_controlled": bool(p.get("is_controlled")), "created_by": U(p.get("created_by")),
        "occurred_at": at, "day": local_day(at),
    }  # fmt: skip
    await _insert_once(session, Movement, values)
    await _upsert(session, StockRow, {
        "branch_id": values["branch_id"], "batch_id": values["batch_id"], "medicine_id": values["medicine_id"],
        "lot_no": values["lot_no"], "expiry_date": values["expiry_date"], "cost_per_base": values["cost_per_base"],
        "qty_on_hand": values["qty_after"], "last_seq": values["seq"], "last_movement_at": at,
    }, ["branch_id", "batch_id"], where=StockRow.last_seq < values["seq"])  # fmt: skip


async def alert(session: AsyncSession, event_type: str, p: dict[str, Any]) -> None:
    kind = event_type.split(".")[1]  # low | expiring
    ref = p.get("batch_id") if kind == "expiring" else p.get("medicine_id")
    await _insert_once(session, Alert, {"kind": kind, "ref": str(ref), "day": date.fromisoformat(p["day"]),
                                        "branch_id": UUID(p["branch_id"]), "medicine_id": UUID(p["medicine_id"]),
                                        "data": p})  # fmt: skip


async def transfer(session: AsyncSession, p: dict[str, Any]) -> None:
    if not p.get("transfer_id"):
        return
    tid, version = UUID(p["transfer_id"]), int(p.get("version") or 0)
    old = await session.get(Transfer, tid)
    if old is not None and old.version >= version:
        return

    def at(key: str) -> datetime | None:
        return datetime.fromisoformat(p[key]) if p.get(key) else None

    await _upsert(session, Transfer, {
        "id": tid, "version": version, "number": p["number"], "from_branch_id": UUID(p["from_branch"]["id"]),
        "to_branch_id": UUID(p["to_branch"]["id"]), "status": p["status"], "created_at": at("created_at"),
        "dispatched_at": at("dispatched_at"), "received_at": at("received_at"), "data": p,
    }, ["id"])  # fmt: skip


async def request(session: AsyncSession, kind: str, p: dict[str, Any]) -> None:
    """Transfer requests wait for the sending branch; purchase requests for a manager."""
    branch = p.get("from_branch_id") if kind == "transfer_request" else p.get("branch_id")
    if not p.get("request_id") or not branch:
        return
    await _upsert(session, PendingRequest, {"id": UUID(p["request_id"]), "kind": kind, "number": p.get("number") or "",
                                            "branch_id": UUID(branch), "status": p.get("status") or "",
                                            "updated_at": when(p.get("occurred_at"))}, ["id"])  # fmt: skip


async def shrinkage(session: AsyncSession, p: dict[str, Any]) -> None:
    await _upsert(session, Shrinkage, {
        "id": UUID(p["shrinkage_id"]), "number": p["number"], "branch_id": UUID(p["branch_id"]),
        "batch_id": UUID(p["batch_id"]), "medicine_id": UUID(p["medicine_id"]), "lot_no": p.get("lot_no") or "",
        "qty_base": int(p["qty_base"]), "reason": p["reason"], "value": D(p["value"]), "status": p["status"],
        "is_controlled": bool(p.get("is_controlled")), "created_by": U(p.get("created_by")),
        "updated_at": when(p.get("occurred_at")),
    }, ["id"])  # fmt: skip


async def count(session: AsyncSession, event_type: str, p: dict[str, Any]) -> None:
    cid, version = UUID(p["count_id"]), int(p.get("version") or 0)
    old = await session.get(Count, cid)
    if old is not None and old.version > version:
        return
    await _upsert(session, Count, {
        "id": cid, "version": version, "number": p["number"], "branch_id": UUID(p["branch_id"]),
        "status": p["status"], "scope": p.get("scope") or "", "variance_value": D(p.get("variance_value")),
        "updated_at": when(p.get("occurred_at")),
    }, ["id"])  # fmt: skip
    if "lines" in p:
        await session.execute(delete(CountLine).where(CountLine.count_id == cid))
        for x in p["lines"]:
            session.add(CountLine(
                id=UUID(x["count_line_id"]), count_id=cid, medicine_id=UUID(x["medicine_id"]), sku=x.get("sku") or "",
                lot_no=x.get("lot_no") or "", expected_qty=int(x.get("expected_qty") or 0),
                counted_qty=int(x.get("counted_qty") or 0), variance=int(x["variance"]),
                cost_per_base=D(x.get("cost_per_base")), value=D(x.get("value")),
                is_controlled=bool(x.get("is_controlled")),
            ))  # fmt: skip


async def register(session: AsyncSession, event_type: str, p: dict[str, Any]) -> None:
    at = when(p.get("occurred_at"))
    if event_type == "register.discrepancy":
        await _insert_once(session, RegisterIssue, {
            "id": p["discrepancy_id"], "kind": "discrepancy", "branch_id": UUID(p["branch_id"]),
            "medicine_id": U(p.get("medicine_id")), "batch_id": U(p.get("batch_id")), "lot_no": p.get("lot_no") or "",
            "register_qty": p.get("register_qty"), "stock_qty": p.get("stock_qty"), "status": "open",
            "found_at": at})  # fmt: skip
    elif event_type == "register.chain_broken":
        await _insert_once(session, RegisterIssue, {
            "id": f"chain:{p['branch_id']}:{p['medicine_id']}:{p.get('first_bad_entry_id')}"[:80], "kind": "chain_broken",
            "branch_id": UUID(p["branch_id"]), "medicine_id": U(p.get("medicine_id")), "batch_id": None,
            "status": "open", "found_at": at})  # fmt: skip
    elif event_type == "register.discrepancy_resolved":
        await session.execute(update(RegisterIssue).where(RegisterIssue.id == p["discrepancy_id"])
                              .values(status=p.get("status") or "resolved", closed_at=at))  # fmt: skip


# ---------------------------------------------------------------- purchasing, customers


async def goods_received(session: AsyncSession, p: dict[str, Any]) -> None:
    at = datetime.fromisoformat(p["received_at"])
    rid, branch, supplier = UUID(p["receipt_id"]), UUID(p["branch_id"]), UUID(p["supplier_id"])
    total = Decimal("0")
    for x in p.get("lines") or []:
        line_total = D(x.get("line_total")) if x.get("line_total") else (D(x["cost_per_base"]) * x["qty_base"]).quantize(
            Decimal("0.01"))  # fmt: skip
        total += line_total
        await _insert_once(session, ReceiptLine, {
            "id": UUID(x["receipt_line_id"]), "receipt_id": rid, "number": p["number"], "branch_id": branch,
            "supplier_id": supplier, "received_at": at, "day": local_day(at), "medicine_id": UUID(x["medicine_id"]),
            "qty_base": int(x["qty_base"]), "lot_no": x["lot_no"], "expiry_date": date.fromisoformat(x["expiry_date"]),
            "cost_per_base": D(x["cost_per_base"]), "line_total": line_total})  # fmt: skip
    if p.get("due_on"):
        due = date.fromisoformat(p["due_on"])
    else:  # receipts from before S8: the supplier's terms
        s = await session.get(Supplier, supplier)
        due = local_day(at) + timedelta(days=s.payment_terms_days if s else 0)
    await _insert_once(session, Bill, {"id": rid, "number": p["number"], "branch_id": branch, "supplier_id": supplier,
                                       "received_on": local_day(at), "due_on": due,
                                       "total": D(p["total"]) if p.get("total") else total})  # fmt: skip


async def supplier_payment(session: AsyncSession, p: dict[str, Any]) -> None:
    pid, branch = UUID(p["payment_id"]), UUID(p["branch_id"])
    supplier = await session.get(Supplier, UUID(p["supplier_id"]))
    paid_on = date.fromisoformat(p["paid_on"])
    amount = D(p["amount"])
    values = {"branch_id": branch, "method": p["method"], "currency": "USD", "reference": p.get("number") or "",
              "party": supplier.name if supplier else "", "staff_id": None}  # fmt: skip
    await _upsert(session, Payment, {**values, "id": f"supplier:{pid}", "kind": "supplier_payment", "day": paid_on,
                                     "occurred_at": datetime.combine(paid_on, datetime.min.time(), clock.TIMEZONE),
                                     "amount": -amount, "amount_usd": -amount}, ["id"])  # fmt: skip
    cancelled = p.get("status") == "cancelled"
    if cancelled:
        at = when(p.get("occurred_at"))
        await _upsert(session, Payment, {**values, "id": f"supplier-cancel:{pid}", "kind": "supplier_payment_cancel",
                                         "day": local_day(at), "occurred_at": at, "amount": amount,
                                         "amount_usd": amount}, ["id"])  # fmt: skip
    for a in p.get("allocations") or []:
        await _upsert(session, BillAllocation, {
            "payment_id": pid, "bill_id": UUID(a["receipt_id"]),
            "amount": Decimal("0") if cancelled or a.get("reversed") else D(a["amount"])},
            ["payment_id", "bill_id"])  # fmt: skip


async def customer_payment(session: AsyncSession, p: dict[str, Any]) -> None:
    pid, branch, customer_id = UUID(p["payment_id"]), UUID(p["branch_id"]), UUID(p["customer_id"])
    customer = await session.get(Customer, customer_id)
    amount = D(p["amount"])
    paid_on = date.fromisoformat(p["paid_on"]) if p.get("paid_on") else local_day(when(p.get("occurred_at")))
    values = {"branch_id": branch, "method": p["method"], "currency": "USD", "reference": p.get("number") or "",
              "party": customer.name if customer else "", "staff_id": None}  # fmt: skip
    await _upsert(session, Payment, {**values, "id": f"customer:{pid}", "kind": "customer_payment", "day": paid_on,
                                     "occurred_at": datetime.combine(paid_on, datetime.min.time(), clock.TIMEZONE),
                                     "amount": amount, "amount_usd": amount}, ["id"])  # fmt: skip
    cancelled = p.get("status") == "cancelled"
    if cancelled:
        at = when(p.get("occurred_at"))
        await _upsert(session, Payment, {**values, "id": f"customer-cancel:{pid}", "kind": "customer_payment_cancel",
                                         "day": local_day(at), "occurred_at": at, "amount": -amount,
                                         "amount_usd": -amount}, ["id"])  # fmt: skip
    for a in p.get("allocations") or []:
        await _upsert(session, DebtAllocation, {
            "payment_id": pid, "invoice_no": a["invoice_no"], "customer_id": customer_id,
            "amount": Decimal("0") if cancelled or a.get("reversed") else D(a["amount"])},
            ["payment_id", "invoice_no"])  # fmt: skip


async def credit_charged(session: AsyncSession, p: dict[str, Any]) -> None:
    await _insert_once(session, Debt, {"invoice_id": UUID(str(p["invoice_id"])), "customer_id": UUID(p["customer_id"]),
                                       "branch_id": UUID(p["branch_id"]), "amount": D(p["amount"]),
                                       "reversed": Decimal("0"), "charged_on": local_day(when(p.get("occurred_at")))})  # fmt: skip


async def credit_reversed(session: AsyncSession, p: dict[str, Any]) -> None:
    invoice_id = UUID(str(p["invoice_id"]))
    key = f"{invoice_id}:{p.get('kind')}:{p['amount']}:{p.get('balance_after')}:{p.get('occurred_at') or ''}"[:120]
    if await _insert_once(session, DebtReversal, {"id": key, "invoice_id": invoice_id, "amount": D(p["amount"])}):
        total = (await session.execute(select(func.coalesce(func.sum(DebtReversal.amount), 0))
                                       .where(DebtReversal.invoice_id == invoice_id))).scalar_one()  # fmt: skip
        await session.execute(update(Debt).where(Debt.invoice_id == invoice_id).values(reversed=total))


async def deposit(session: AsyncSession, p: dict[str, Any]) -> None:
    """A sale order's deposit: money in when taken, out when refunded."""
    did, branch = UUID(p["deposit_id"]), UUID(p["branch_id"])
    customer = await session.get(Customer, UUID(p["customer_id"]))
    taken = when(p.get("created_at"))
    values = {"branch_id": branch, "method": p.get("method") or "cash", "currency": "USD",
              "reference": p.get("document_no") or "", "party": customer.name if customer else "", "staff_id": None}  # fmt: skip
    amount = D(p["amount"])
    await _upsert(session, Payment, {**values, "id": f"deposit:{did}", "kind": "deposit", "day": local_day(taken),
                                     "occurred_at": taken, "amount": amount, "amount_usd": amount}, ["id"])  # fmt: skip
    if p.get("status") == "refunded":
        at = when(p.get("occurred_at"))
        back = amount - D(p.get("used"))
        await _upsert(session, Payment, {**values, "id": f"deposit-refund:{did}", "kind": "deposit_refund",
                                         "day": local_day(at), "occurred_at": at, "amount": -back,
                                         "amount_usd": -back}, ["id"])  # fmt: skip


# ---------------------------------------------------------------- commission, modifications


async def commission_line(session: AsyncSession, p: dict[str, Any]) -> None:
    await _insert_once(session, CommissionLine, {
        "id": UUID(p["line_id"]), "period_id": UUID(p["period_id"]), "month": date.fromisoformat(p["month"]),
        "branch_id": UUID(p["branch_id"]), "staff_id": UUID(p["staff_id"]), "invoice_number": p["invoice_number"],
        "source": p["source"], "medicine_id": UUID(p["medicine_id"]), "sku": p["sku"], "qty_base": int(p["qty_base"]),
        "net_usd": D(p["net_usd"]), "amount": D(p["amount"]), "created_at": datetime.fromisoformat(p["created_at"]),
    })  # fmt: skip


async def modification(session: AsyncSession, p: dict[str, Any], message_id: UUID) -> None:
    if p.get("service") != "catalog" or p.get("entity_type") not in MODIFIED:
        return
    before, after = p.get("before") or {}, p.get("after") or {}
    changed = [{"field": k, "old": before.get(k), "new": after.get(k)}
               for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]  # fmt: skip
    at = when(None)
    await _insert_once(session, Modification, {
        "id": message_id, "occurred_at": at, "day": local_day(at), "action": p.get("action") or "",
        "entity_type": p["entity_type"], "entity_id": p.get("entity_id"), "actor_id": U(p.get("actor_id")),
        "branch_id": U(p.get("branch_id")), "changes": changed})  # fmt: skip
