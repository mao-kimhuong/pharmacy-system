"""The sale saga (POST /invoices). Steps, and what undoes each:

  1. validate         active products, price from the local copy, qty in pack
                      units → base units; Rx-only → needs rx_item_id (RX_REQUIRED)
                      and a pharmacist with pos.dispense_rx (PHARMACIST_REQUIRED); an
                      allergy override also needs prescriptions.override_warning;
                      controlled → also controlled.dispense, the patient's ID
                      document and the pharmacist's PIN (pin_token, consumed here);
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
    KhqrPayment,
    KnownBranch,
    OutboxEvent,
    SaleOrder,
)
from . import checks, commission, khqr, promotions
from .clients import Clients
from .common import audit, clean
from .snapshot import invoice_payload

log = logging.getLogger(__name__)
# Errors meaning "nothing (more) to undo there".
NOTHING_TO_UNDO = {ErrorCode.INVOICE_STATE, ErrorCode.NOT_FOUND}
CLIENT_STATUS = {
    ErrorCode.OUT_OF_STOCK: 409, ErrorCode.BATCH_EXPIRED: 409, ErrorCode.BATCH_BLOCKED: 409,
    ErrorCode.TEMPORARILY_UNAVAILABLE: 503, ErrorCode.PHARMACIST_REQUIRED: 403,
    ErrorCode.ALLERGY_WARNING: 409, ErrorCode.DUPLICATE_THERAPY_WARNING: 409, ErrorCode.PRESCRIPTION_STATE: 409,
    ErrorCode.BELOW_COST: 422, ErrorCode.DISCOUNT_APPROVAL_REQUIRED: 403, ErrorCode.PROMOTION_LIMIT: 409,
    ErrorCode.DEPOSIT_EXCEEDED: 409,
}  # fmt: skip


LinePlan = checks.LinePlan


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


async def order_hold(session: AsyncSession, inv: Invoice) -> UUID | None:
    """The reservation of the sale order this invoice came from, while the order
    still holds stock (open, reservation not released, reserve_until not passed)."""
    if inv.sale_order_id is None:
        return None
    order = await session.get(SaleOrder, inv.sale_order_id, populate_existing=True)
    if (order is None or order.status not in ("ordered", "partly_fulfilled") or order.reservation_id is None
            or order.reservation_released_at is not None or order.reserve_until is None
            or order.reserve_until <= clock.now()):  # fmt: skip
        return None
    return order.reservation_id


async def compensate(
    inv: Invoice, actor: CurrentUser | None, clients: Clients, back_to: UUID | None = None
) -> list[str]:
    """Undo whatever reached inventory and customers for this invoice. Safe to
    repeat. Returns the problems (empty = all undone). back_to: the sale order's
    reservation, which gets the held stock back instead of releasing it."""
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
    if back_to is not None:
        problems.append(await _undo("give the stock back to the order", lambda: clients.inventory.post(
            f"/reservations/{back_to}/merge-back", {"ref_id": str(inv.id)}, actor=actor,
            branch_id=inv.branch_id)))  # fmt: skip
    problems.append(await _undo("release stock", lambda: clients.inventory.post(
        "/reservations/release-by-ref", {"ref_type": "invoice", "ref_id": str(inv.id)},
        actor=actor, branch_id=inv.branch_id)))  # fmt: skip
    for pay in [p for p in inv.payments if p.method == "deposit" and p.deposit_id]:
        problems.append(await _undo("give back the deposit", lambda pay=pay: clients.customers.post(
            f"/deposits/{pay.deposit_id}/unuse", {"invoice_id": str(inv.id), "reason": "sale not completed"},
            actor=actor, branch_id=inv.branch_id)))  # fmt: skip
    return [p for p in problems if p]


async def khqr_refunds(session: AsyncSession, inv: Invoice, reason: str, source: str = "failed_sale") -> None:
    """KHQR money of a sale that did not complete (or was cancelled): a refund due (the refund button)."""
    for pay in [p for p in inv.payments if p.khqr_id]:
        row = await session.get(KhqrPayment, pay.khqr_id, with_for_update=True)
        if row is not None and row.status == "used":
            khqr.needs_refund(session, row, reason, source=source,
                              ref=f"{'cancel' if source == 'invoice_cancel' else 'invoice'}:{inv.id}")  # fmt: skip


async def _fail(
    session: AsyncSession, inv_id: UUID, actor: CurrentUser | None, err: AppError, clients: Clients
) -> None:
    await session.rollback()
    inv = await session.get(Invoice, inv_id, populate_existing=True)
    problems = await compensate(inv, actor, clients, await order_hold(session, inv))
    inv.status = "needs_attention" if problems else "failed"
    await promotions.set_status(session, inv.id, "released")
    await khqr_refunds(session, inv, err.message)
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
    session: AsyncSession,
    actor: CurrentUser,
    data: dict[str, Any],
    idempotency_key: str,
    clients: Clients,
    *,
    order: Any = None,
) -> Invoice:
    existing = (await session.execute(select(Invoice).where(
        Invoice.created_by == actor.id, Invoice.idempotency_key == idempotency_key))).scalar_one_or_none()  # fmt: skip
    if existing is not None:
        return await _replay(existing)

    # 1. validate, price, settle (the same checks as the cart preview, raising)
    result = await checks.run_checks(session, actor, clients, data, "raise", order=order)
    branch, customer, lines = result.branch, result.customer, result.lines
    pharmacist, approver, rate, s = result.pharmacist, result.approver, result.rate, result.settlement
    subtotal, discount, total = result.subtotal, result.discount, result.total

    inv = Invoice(
        branch_id=branch.id, customer_id=customer.id if customer else None, status="pending",
        created_by=actor.id, idempotency_key=idempotency_key, note=clean(data.get("note")),
        subtotal=subtotal, discount=discount, total=total, paid=s.paid, credit_amount=s.credit,
        sale_order_id=order.id if order else None,
        change_usd=s.change_usd, khr_per_usd=rate.khr_per_usd if rate else None, total_khr=s.total_khr,
        change_in=data.get("change_in") or "USD_KHR", change_given_usd=s.change_given_usd,
        change_given_khr=s.change_given_khr, change_rounding_khr=s.change_rounding_khr, version=1,
        lines=[InvoiceLine(
            line_no=x.line_no, medicine_id=x.pack.product_id, pack_unit_id=x.pack.id, sku=x.pack.product.sku,
            name=x.pack.product.display_name, name_km=x.pack.product.name_km, pack_unit=x.pack.name, qty=x.qty,
            qty_in_base=x.pack.qty_in_base, qty_base=x.qty_base, unit_price=x.unit_price, line_total=x.line_total,
            batch_override_id=x.batch_id, override_reason=x.override_reason, rx_item_id=x.rx_item_id,
            allergy_override_reason=x.allergy_override_reason, is_controlled=x.controlled,
            patient_id_document=x.patient_id_document, pin_confirmed_by=actor.id if x.controlled else None,
            promotion_ids=x.promotion_ids, promo_discount=x.promo_discount, manual_discount=x.manual_discount,
            manual_discount_by=approver if x.manual_discount > 0 else None, is_hamper=x.pack.product.is_hamper,
            order_line_id=x.order_line.id if x.order_line else None,
        ) for x in lines],
        payments=[InvoicePayment(seq=i, method=p.method, currency=p.currency, amount=p.amount, amount_usd=u,
                                 deposit_id=raw.get("deposit_id") if p.method == "deposit" else None,
                                 khqr_id=raw.get("khqr_id") if p.method == "KHQR" else None)
                  for i, ((p, u), raw) in enumerate(zip(s.payments, data["payments"], strict=True), start=1)],
    )  # fmt: skip
    session.add(inv)
    try:
        await session.flush()
        for paid in result.khqr:  # locked by the checks: this sale uses it, once
            paid.status, paid.invoice_id = "used", inv.id
        await promotions.hold(
            session, inv.id, inv.customer_id, {UUID(p) for x in lines for p in x.promotion_ids}
        )
        await session.commit()
    except IntegrityError as exc:  # the same key sent twice at the same moment
        await session.rollback()
        raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "This sale is already being processed",
                       status_code=409) from exc  # fmt: skip
    except AppError:
        await session.rollback()
        raise
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
        if order is not None and order.reservation_id and order.reservation_released_at is None:
            # the order's reserved batches move to this invoice (nothing released in between)
            reservation = await clients.inventory.post(f"/reservations/{order.reservation_id}/split", {
                "ref_id": str(inv_id), "lines": [{"from_line_no": x.order_line.line_no, "to_line_no": x.line_no,
                                                  "qty_base": x.qty_base} for x in lines]},
                actor=actor, branch_id=branch.id)  # fmt: skip
        else:
            reservation = await clients.inventory.post("/reservations", {
                "ref_type": "invoice", "ref_id": str(inv_id), "branch_id": str(branch.id),
                "lines": [{"line_no": x.line_no, "medicine_id": str(x.pack.product_id), "qty_base": x.qty_base,
                           **({"batch_id": str(x.batch_id)} if x.batch_id else {}),
                           **({"meta": controlled_meta(inv, x.line_no, pharmacist)} if x.controlled else {})}
                          for x in lines],
            }, actor=actor, branch_id=branch.id, idempotency_key=f"{idempotency_key}:reserve")  # fmt: skip
        inv.reservation_id = UUID(str(reservation["id"]))
        await session.commit()
        below = checks.below_cost(actor, lines, reservation, checks.Checks("raise"))
        # 3b. pay with a sale order's deposit – undone by deposits/{id}/unuse
        for pay in [p for p in inv.payments if p.method == "deposit"]:
            await clients.customers.post(f"/deposits/{pay.deposit_id}/use", {
                "invoice_id": str(inv_id), "customer_id": str(inv.customer_id), "amount": str(pay.amount_usd),
            }, actor=actor, branch_id=branch.id)  # fmt: skip
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
        await _finish(session, actor, inv, branch, confirmed, below)
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


def controlled_meta(inv: Invoice, line_no: int, pharmacist: Any = None) -> dict[str, Any]:
    """What the controlled-drug register records with the stock movement."""
    line = next(x for x in inv.lines if x.line_no == line_no)
    return {
        "entry_type": None, "invoice_id": str(inv.id), "rx_item_id": str(line.rx_item_id),
        "prescription_id": str(line.prescription_id) if line.prescription_id else None,
        "prescription_number": line.prescription_number, "patient_id": str(line.patient_id) if line.patient_id else None,
        "patient_name": line.patient_name_en or line.patient_name_km, "patient_id_document": line.patient_id_document,
        "pharmacist_id": str(line.pin_confirmed_by or inv.created_by),
        "pharmacist_name": pharmacist.name if pharmacist else "", "pin_confirmed": True,
    }  # fmt: skip


def _apply_rx(inv: Invoice, actor: CurrentUser, held: list[dict[str, Any]]) -> None:
    """The Rx, patient, directions and warnings onto the lines; who accepted the
    warnings, and when (also in the User Log when the sale completes)."""
    by_line = {x["line_no"]: x for x in held}
    for line in inv.lines:
        h = by_line.get(line.line_no)
        if h is None:
            continue
        line.prescription_id, line.prescription_number = (
            UUID(str(h["prescription_id"])),
            h["prescription_number"],
        )
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
    session: AsyncSession,
    actor: CurrentUser,
    inv: Invoice,
    branch: KnownBranch,
    confirmed: dict,
    below: list[str] | None = None,
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
            medicine_id=UUID(str(b["medicine_id"])) if line.is_hamper else None,
        ) for i, b in enumerate(used, start=1))  # fmt: skip
        line.cost = sum((Decimal(str(b["cost_per_base"])) * b["qty_base"] for b in used), Decimal("0"))
    await session.flush()
    for line in inv.lines:
        await session.refresh(line, attribute_names=["batches"])
    inv.number = await next_number(session, DocSequence, branch.id, branch.code, "INV")
    inv.status = "completed"
    inv.completed_at = clock.now()
    await session.flush()
    await promotions.set_status(session, inv.id, "used")
    await commission.record_sale(session, inv)
    if inv.sale_order_id:
        from .orders import after_invoice  # orders imports this module

        await after_invoice(session, actor, inv)
    add_event(session, OutboxEvent, "invoice.created", await invoice_payload(session, inv))
    audit(session, actor, "invoice.created", "invoice", inv.id, branch_id=inv.branch_id, after={
        "number": inv.number, "total": str(inv.total), "credit": str(inv.credit_amount),
        "payments": [f"{p.method} {p.amount} {p.currency}" for p in inv.payments],
        "lines": [f"{x.qty} x {x.sku} {x.pack_unit} @ {x.unit_price}" for x in inv.lines],
        "batch_overrides": [f"line {x.line_no}: {x.override_reason}" for x in inv.lines if x.batch_override_id],
        "khr_per_usd": inv.khr_per_usd, "change_given": f"{inv.change_given_usd} USD + {inv.change_given_khr} KHR",
        "prescriptions": [f"line {x.line_no}: {x.prescription_number}" for x in inv.lines if x.rx_item_id],
        "discount": str(inv.discount),
        "promotions": sorted({p for x in inv.lines for p in x.promotion_ids}),
        "manual_discounts": [f"line {x.line_no}: {x.manual_discount}" for x in inv.lines if x.manual_discount],
        "discount_approved_by": next((str(x.manual_discount_by) for x in inv.lines if x.manual_discount_by), None),
        "below_cost": below or None,
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
