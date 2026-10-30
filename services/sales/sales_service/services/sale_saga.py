"""The sale saga (POST /invoices). Steps, and what undoes each:

  1. validate         active products, price from the local copy, qty in pack
                      units → base units; controlled → CONTROLLED_NOT_AVAILABLE
                      (until S5); Rx-only → needs rx_item_id (RX_REQUIRED) and a
                      pharmacist with pos.dispense_rx (PHARMACIST_REQUIRED); an
                      allergy override also needs prescriptions.override_warning;
                      payments settle (money.py). Saved as "pending" (no number).
  1b. Rx check + hold prescription: state, valid date, quantity, allergy,
                      duplicate therapy; holds the quantity    ← rx/release
  2. reserve stock    inventory, FEFO, row-locked          ← release (by invoice)
  3. charge credit    customers, credit-limit check        ← reverse the charge
  4. confirm stock    inventory "out" movements            ← reverse ("sale_cancel")
  5. finish           number PP1-INV-2026-000123 (no gaps: only completed sales
                      get one), batches used per line, invoice.created, User Log.

Any failure runs the compensations in reverse order. Each compensation is
registered BEFORE its step runs and is idempotent, so a step whose outcome is
unknown (timeout) is undone too, and running one that has nothing to undo is
harmless. The invoice ends "failed" with the reason, nothing half-done; if a
compensation itself cannot run (a service is down) the invoice is
"needs_attention" and the recovery task finishes it.

The same Idempotency-Key gives the same invoice (also after a crash: the key is
stored on the invoice).
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.numbering import next_number
from pharmacy_shared.outbox import add_event

from ..models import (
    DocSequence,
    Invoice,
    InvoiceLine,
    InvoiceLineBatch,
    InvoicePayment,
    KnownBranch,
    KnownCustomer,
    OutboxEvent,
    ProductPackUnit,
)
from . import money, rates
from .clients import Clients
from .common import audit, branch_for, clean
from .snapshot import invoice_payload

log = logging.getLogger(__name__)
# Errors meaning "nothing (more) to undo there".
NOTHING_TO_UNDO = {ErrorCode.INVOICE_STATE, ErrorCode.NOT_FOUND}
CLIENT_STATUS = {
    ErrorCode.OUT_OF_STOCK: 409, ErrorCode.BATCH_EXPIRED: 409, ErrorCode.BATCH_BLOCKED: 409,
    ErrorCode.TEMPORARILY_UNAVAILABLE: 503, ErrorCode.PHARMACIST_REQUIRED: 403,
    ErrorCode.ALLERGY_WARNING: 409, ErrorCode.DUPLICATE_THERAPY_WARNING: 409, ErrorCode.PRESCRIPTION_STATE: 409,
}  # fmt: skip


@dataclass
class LinePlan:
    line_no: int
    pack: ProductPackUnit
    qty: int
    qty_base: int
    unit_price: Decimal
    line_total: Decimal
    batch_id: UUID | None
    override_reason: str | None
    rx_item_id: UUID | None = None
    allergy_override_reason: str | None = None
    acknowledge_warnings: bool = False


# ---------------------------------------------------------------- 1. validate


async def _plan_lines(session: AsyncSession, actor: CurrentUser, raw: list[dict[str, Any]]) -> list[LinePlan]:
    plans = []
    for i, item in enumerate(raw, start=1):
        pack = (
            await session.execute(select(ProductPackUnit).where(ProductPackUnit.id == item["pack_unit_id"]))
        ).scalar_one_or_none()
        details = {"line": i}
        if pack is None or pack.product_id != item["medicine_id"]:
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: unknown medicine or pack unit", status_code=422,
                           details=details)  # fmt: skip
        product = pack.product
        if not (pack.is_active and product.is_active):
            raise AppError(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: {product.sku} ({pack.name}) is not sold any more",
                           status_code=422, details=details)  # fmt: skip
        if product.controlled_schedule:
            raise AppError(
                ErrorCode.CONTROLLED_NOT_AVAILABLE,
                f"Line {i}: {product.display_name} is a controlled medicine (schedule {product.controlled_schedule}). "
                "Controlled sales need the controlled-drug register, coming in sprint S5.",
                status_code=422, details={**details, "medicine_id": str(product.id)},
            )  # fmt: skip
        rx_item_id = item.get("rx_item_id")
        if product.is_rx_only and rx_item_id is None:
            raise AppError(
                ErrorCode.RX_REQUIRED,
                f"Line {i}: {product.display_name} is prescription-only: choose the patient's prescription",
                status_code=422, details={**details, "medicine_id": str(product.id)},
            )  # fmt: skip
        allergy_reason = clean(item.get("allergy_override_reason")) or None
        if rx_item_id is not None and not (actor.is_pharmacist and actor.has("pos.dispense_rx")):
            raise AppError(ErrorCode.PHARMACIST_REQUIRED, f"Line {i}: only a pharmacist may dispense a prescription",
                           status_code=403, details=details)  # fmt: skip
        if allergy_reason and not (actor.is_pharmacist and actor.has("prescriptions.override_warning")):
            raise AppError(ErrorCode.PHARMACIST_REQUIRED,
                           f"Line {i}: only a pharmacist allowed to override warnings may sell despite an allergy",
                           status_code=403, details=details)  # fmt: skip
        if allergy_reason and rx_item_id is None:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {i}: an allergy override needs the prescription",
                           status_code=422, details=details)  # fmt: skip
        batch_id = item.get("batch_id")
        reason = clean(item.get("override_reason")) or None
        if batch_id is not None:
            if not actor.is_pharmacist:
                raise AppError(ErrorCode.PHARMACIST_REQUIRED, f"Line {i}: only a pharmacist may choose the batch",
                               status_code=403, details=details)  # fmt: skip
            if not reason:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"Line {i}: give the reason for choosing this batch",
                               status_code=422, details={**details, "field": "override_reason"})  # fmt: skip
        price = pack.sell_price
        plans.append(LinePlan(line_no=i, pack=pack, qty=item["qty"], qty_base=item["qty"] * pack.qty_in_base,
                              unit_price=price, line_total=money.usd(price * item["qty"]), batch_id=batch_id,
                              override_reason=reason, rx_item_id=rx_item_id, allergy_override_reason=allergy_reason,
                              acknowledge_warnings=bool(item.get("acknowledge_warnings"))))  # fmt: skip
    return plans


async def _customer(session: AsyncSession, customer_id: UUID | None) -> KnownCustomer | None:
    if customer_id is None:
        return None
    customer = await session.get(KnownCustomer, customer_id)
    if customer is None or not customer.is_active:
        raise AppError(ErrorCode.CUSTOMER_REQUIRED, "Unknown or deactivated customer", status_code=422)
    return customer


# ---------------------------------------------------------------- compensations


async def _undo(step: str, call) -> str | None:  # noqa: ANN001
    """Run one compensation; None when done (or nothing to undo), else why not."""
    try:
        await call()
        return None
    except AppError as err:
        if err.code in NOTHING_TO_UNDO:
            return None
        log.warning("compensation %s failed: %s %s", step, err.code, err.message)
        return f"{step}: {err.code} {err.message}"


async def compensate(inv: Invoice, actor: CurrentUser | None, clients: Clients) -> list[str]:
    """Undo whatever reached inventory and customers for this invoice. Safe to
    repeat. Returns the problems (empty = all undone)."""
    problems = []
    if any(x.rx_item_id for x in inv.lines):
        problems.append(await _undo("release prescription", lambda: clients.prescription.post(
            "/rx/release", {"invoice_id": str(inv.id)}, actor=actor, branch_id=inv.branch_id)))  # fmt: skip
    if inv.reservation_id is not None:
        problems.append(await _undo("return stock", lambda: clients.inventory.post(
            f"/reservations/{inv.reservation_id}/reverse", {"reason": f"Sale {inv.id} undone"},
            actor=actor, branch_id=inv.branch_id)))  # fmt: skip
    if inv.credit_amount > 0 and inv.customer_id is not None:
        problems.append(await _undo("reverse credit", lambda: clients.customers.post("/credit/reverse", {
            "invoice_id": str(inv.id), "customer_id": str(inv.customer_id), "branch_id": str(inv.branch_id),
            "kind": "cancel", "reason": "sale not completed"}, actor=actor, branch_id=inv.branch_id)))  # fmt: skip
    problems.append(await _undo("release stock", lambda: clients.inventory.post(
        "/reservations/release-by-ref", {"ref_type": "invoice", "ref_id": str(inv.id)},
        actor=actor, branch_id=inv.branch_id)))  # fmt: skip
    return [p for p in problems if p]


async def _fail(
    session: AsyncSession, inv_id: UUID, actor: CurrentUser | None, err: AppError, clients: Clients
) -> None:
    await session.rollback()
    inv = await session.get(Invoice, inv_id, populate_existing=True)
    problems = await compensate(inv, actor, clients)
    inv.status = "needs_attention" if problems else "failed"
    inv.failure_code = err.code.value if isinstance(err.code, ErrorCode) else str(err.code)
    inv.failure_reason = (err.message + (" | not undone yet: " + "; ".join(problems) if problems else ""))[
        :500
    ]
    audit(session, actor, "invoice.failed", "invoice", inv.id, branch_id=inv.branch_id,
          after={"status": inv.status, "code": inv.failure_code, "reason": inv.failure_reason})  # fmt: skip
    await session.commit()


# ---------------------------------------------------------------- the saga


async def _replay(inv: Invoice) -> Invoice:
    if inv.status in ("completed", "cancelling", "cancelled"):
        return inv
    if inv.status in ("failed", "needs_attention"):
        code = (
            ErrorCode(inv.failure_code)
            if inv.failure_code in ErrorCode.__members__
            else ErrorCode.VALIDATION_ERROR
        )
        raise AppError(code, inv.failure_reason or "This sale failed", status_code=CLIENT_STATUS.get(code, 422),
                       details={"invoice_id": str(inv.id)})  # fmt: skip
    raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "This sale is still being processed", status_code=409,
                   details={"invoice_id": str(inv.id)})  # fmt: skip


async def create_invoice(
    session: AsyncSession, actor: CurrentUser, data: dict[str, Any], idempotency_key: str, clients: Clients
) -> Invoice:
    existing = (await session.execute(select(Invoice).where(
        Invoice.created_by == actor.id, Invoice.idempotency_key == idempotency_key))).scalar_one_or_none()  # fmt: skip
    if existing is not None:
        return await _replay(existing)

    # 1. validate
    branch = await branch_for(session, actor, data["branch_id"])
    customer = await _customer(session, data.get("customer_id"))
    lines = await _plan_lines(session, actor, data["lines"])
    payments = [
        money.PaymentIn(p["method"], p["currency"], Decimal(str(p["amount"]))) for p in data["payments"]
    ]
    if any(p.method == "credit" for p in payments) and customer is None:
        raise AppError(ErrorCode.CUSTOMER_REQUIRED, "Choose the customer for a credit sale", status_code=422)
    total = sum((x.line_total for x in lines), Decimal("0.00"))
    rate = await rates.current(session, branch.id)
    s = money.settle(total, payments, rate.khr_per_usd if rate else None, data.get("change_in") or "USD_KHR")

    inv = Invoice(
        branch_id=branch.id, customer_id=customer.id if customer else None, status="pending",
        created_by=actor.id, idempotency_key=idempotency_key, note=clean(data.get("note")),
        subtotal=total, discount=Decimal("0.00"), total=total, paid=s.paid, credit_amount=s.credit,
        change_usd=s.change_usd, khr_per_usd=rate.khr_per_usd if rate else None, total_khr=s.total_khr,
        change_in=data.get("change_in") or "USD_KHR", change_given_usd=s.change_given_usd,
        change_given_khr=s.change_given_khr, change_rounding_khr=s.change_rounding_khr, version=1,
        lines=[InvoiceLine(
            line_no=x.line_no, medicine_id=x.pack.product_id, pack_unit_id=x.pack.id, sku=x.pack.product.sku,
            name=x.pack.product.display_name, name_km=x.pack.product.name_km, pack_unit=x.pack.name, qty=x.qty,
            qty_in_base=x.pack.qty_in_base, qty_base=x.qty_base, unit_price=x.unit_price, line_total=x.line_total,
            batch_override_id=x.batch_id, override_reason=x.override_reason, rx_item_id=x.rx_item_id,
            allergy_override_reason=x.allergy_override_reason,
        ) for x in lines],
        payments=[InvoicePayment(seq=i, method=p.method, currency=p.currency, amount=p.amount, amount_usd=u)
                  for i, (p, u) in enumerate(s.payments, start=1)],
    )  # fmt: skip
    session.add(inv)
    try:
        await session.commit()
    except IntegrityError as exc:  # the same key sent twice at the same moment
        await session.rollback()
        raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "This sale is already being processed",
                       status_code=409) from exc  # fmt: skip
    inv_id = inv.id

    try:
        # 1b. prescriptions: check and hold – undone by rx/release, registered in compensate()
        if any(x.rx_item_id for x in lines):
            held = await clients.prescription.post("/rx/check-and-hold", {
                "invoice_id": str(inv_id), "branch_id": str(branch.id),
                "lines": [{"line_no": x.line_no, "rx_item_id": str(x.rx_item_id),
                           "medicine_id": str(x.pack.product_id), "qty_base": x.qty_base,
                           "allergy_override_reason": x.allergy_override_reason,
                           "acknowledge_warnings": x.acknowledge_warnings} for x in lines if x.rx_item_id],
            }, actor=actor, branch_id=branch.id, idempotency_key=f"{idempotency_key}:rx")  # fmt: skip
            _apply_rx(inv, actor, held["lines"])
            await session.commit()
        # 2. reserve stock (FEFO) – undone by release-by-ref, registered in compensate()
        reservation = await clients.inventory.post("/reservations", {
            "ref_type": "invoice", "ref_id": str(inv_id), "branch_id": str(branch.id),
            "lines": [{"line_no": x.line_no, "medicine_id": str(x.pack.product_id), "qty_base": x.qty_base,
                       **({"batch_id": str(x.batch_id)} if x.batch_id else {})} for x in lines],
        }, actor=actor, branch_id=branch.id, idempotency_key=f"{idempotency_key}:reserve")  # fmt: skip
        inv.reservation_id = UUID(str(reservation["id"]))
        await session.commit()
        # 3. charge credit – undone by credit/reverse
        if s.credit > 0:
            await clients.customers.post("/credit/charge", {
                "invoice_id": str(inv_id), "invoice_no": "", "customer_id": str(customer.id),
                "branch_id": str(branch.id), "amount": str(s.credit),
            }, actor=actor, branch_id=branch.id, idempotency_key=f"{idempotency_key}:charge")  # fmt: skip
        # 4. confirm stock – undone by reservations/{id}/reverse
        confirmed = await clients.inventory.post(f"/reservations/{inv.reservation_id}/confirm", {},
                                                 actor=actor, branch_id=branch.id)  # fmt: skip
        # 5. finish
        await _finish(session, actor, inv, branch, confirmed)
    except AppError as err:
        await _fail(session, inv_id, actor, err, clients)
        raise
    except Exception as exc:  # a bug or the database: undo, then report
        log.exception("sale %s failed", inv_id)
        await _fail(
            session, inv_id, actor, AppError(ErrorCode.TEMPORARILY_UNAVAILABLE, str(exc)[:200], 503), clients
        )
        raise
    if inv.credit_amount > 0:
        # The sale is done; tell customers its number (invoice.created does it too, if this fails).
        try:
            await clients.customers.post(
                "/credit/number", {"invoice_id": str(inv.id), "invoice_no": inv.number},
                actor=actor, branch_id=inv.branch_id,
            )  # fmt: skip
        except AppError:
            log.warning("could not send the number of %s to customers; invoice.created will", inv.number)
    return inv


def _apply_rx(inv: Invoice, actor: CurrentUser, held: list[dict[str, Any]]) -> None:
    """The Rx, patient, directions and warnings onto the lines; who accepted the
    warnings, and when (also in the User Log when the sale completes)."""
    by_line = {x["line_no"]: x for x in held}
    for line in inv.lines:
        h = by_line.get(line.line_no)
        if h is None:
            continue
        line.prescription_id, line.prescription_number = UUID(str(h["prescription_id"])), h["prescription_number"]
        line.patient_id = UUID(str(h["patient_id"]))
        line.patient_name_en, line.patient_name_km = h["patient_name_en"], h["patient_name_km"]
        line.doctor_name, line.dosage, line.frequency = h["doctor_name"], h["dosage"], h["frequency"]
        line.duration_days = h["duration_days"]
        line.warnings = h["warnings"] or None
        kinds = {w["kind"] for w in h["warnings"]}
        if "allergy" in kinds:
            line.allergy_override_by = actor.id
        else:
            line.allergy_override_reason = None
        if "duplicate_therapy" in kinds:
            line.warnings_acknowledged_by, line.warnings_acknowledged_at = actor.id, clock.now()
        inv.patient_id = inv.patient_id or line.patient_id


async def _finish(
    session: AsyncSession, actor: CurrentUser, inv: Invoice, branch: KnownBranch, confirmed: dict
) -> None:
    by_line: dict[int, list[dict]] = {}
    for x in confirmed["lines"]:
        by_line.setdefault(x["line_no"], []).append(x)
    for line in inv.lines:
        used = by_line.get(line.line_no, [])
        session.add_all(InvoiceLineBatch(
            line_id=line.id, seq=i, batch_id=UUID(str(b["batch_id"])), lot_no=b["lot_no"],
            expiry_date=date.fromisoformat(str(b["expiry_date"])), qty_base=b["qty_base"],
            cost_per_base=Decimal(str(b["cost_per_base"])),
        ) for i, b in enumerate(used, start=1))  # fmt: skip
        line.cost = sum((Decimal(str(b["cost_per_base"])) * b["qty_base"] for b in used), Decimal("0"))
    await session.flush()
    for line in inv.lines:
        await session.refresh(line, attribute_names=["batches"])
    inv.number = await next_number(session, DocSequence, branch.id, branch.code, "INV")
    inv.status = "completed"
    inv.completed_at = clock.now()
    await session.flush()
    add_event(session, OutboxEvent, "invoice.created", await invoice_payload(session, inv))
    audit(session, actor, "invoice.created", "invoice", inv.id, branch_id=inv.branch_id, after={
        "number": inv.number, "total": str(inv.total), "credit": str(inv.credit_amount),
        "payments": [f"{p.method} {p.amount} {p.currency}" for p in inv.payments],
        "lines": [f"{x.qty} x {x.sku} {x.pack_unit} @ {x.unit_price}" for x in inv.lines],
        "batch_overrides": [f"line {x.line_no}: {x.override_reason}" for x in inv.lines if x.batch_override_id],
        "khr_per_usd": inv.khr_per_usd, "change_given": f"{inv.change_given_usd} USD + {inv.change_given_khr} KHR",
        "prescriptions": [f"line {x.line_no}: {x.prescription_number}" for x in inv.lines if x.rx_item_id],
    })  # fmt: skip
    for x in inv.lines:
        if x.allergy_override_by:
            audit(session, actor, "dispensing.allergy_override", "invoice", inv.id, branch_id=inv.branch_id, after={
                "number": inv.number, "line": x.line_no, "medicine": x.sku, "prescription": x.prescription_number,
                "patient_id": str(x.patient_id), "reason": x.allergy_override_reason,
                "warnings": [w["en"] for w in x.warnings or [] if w["kind"] == "allergy"]})  # fmt: skip
        if x.warnings_acknowledged_by:
            audit(session, actor, "dispensing.warning_acknowledged", "invoice", inv.id, branch_id=inv.branch_id,
                  after={"number": inv.number, "line": x.line_no, "medicine": x.sku,
                         "prescription": x.prescription_number, "patient_id": str(x.patient_id),
                         "acknowledged_at": x.warnings_acknowledged_at.isoformat(),
                         "warnings": [w["en"] for w in x.warnings or [] if w["kind"] == "duplicate_therapy"]})  # fmt: skip
    await session.commit()
