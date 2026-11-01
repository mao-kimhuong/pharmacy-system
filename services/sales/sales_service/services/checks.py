"""One check engine for the cart preview and the sale saga.

run_checks(mode="raise") IS step 1 of the saga (validate, price, settle): it
raises the first problem as the same AppError as always, and does the two side
effects of that step (the pharmacist's PIN and a discount approver's PIN are
consumed). run_checks(mode="collect") runs the same rules for the preview: it
gathers every finding and has no side effects (no PIN is consumed).

The preview then asks the read-only twins of the later saga steps:
prescription /rx/check, inventory /reservations/plan (→ BELOW_COST from the
batches' cost) and customers /customers/{id}/credit (the saga's credit step is
the customers service's own check).

Finding severities: hard_stop (cannot post), requirement (posting needs
something the preview must not consume: the pharmacist's PIN, the patient's ID
document, a discount approval), warning (Rx warnings; resolved when the line
carries the override / acknowledgement), info (a batch close to expiry).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.pin import consume_pin

from ..models import BranchSettingsCopy, KnownCustomer, ProductPackUnit
from . import cart, khqr, money, rates
from .clients import Clients
from .common import branch_for, clean

Mode = Literal["raise", "collect"]
WARNINGS = {ErrorCode.ALLERGY_WARNING, ErrorCode.DUPLICATE_THERAPY_WARNING}
KM = {
    ErrorCode.UNKNOWN_MEDICINE: "មិនស្គាល់ឱសថ ឬឈប់លក់ហើយ",
    ErrorCode.RX_REQUIRED: "ត្រូវការវេជ្ជបញ្ជា",
    ErrorCode.PHARMACIST_REQUIRED: "ត្រូវការឱសថការី",
    ErrorCode.VALIDATION_ERROR: "ព័ត៌មានមិនគ្រប់គ្រាន់",
    ErrorCode.PIN_REQUIRED: "ត្រូវការលេខ PIN របស់ឱសថការី",
    ErrorCode.CUSTOMER_REQUIRED: "សូមជ្រើសរើសអតិថិជន",
    ErrorCode.EXCHANGE_RATE_MISSING: "មិនទាន់កំណត់អត្រាប្តូរប្រាក់",
    ErrorCode.DISCOUNT_APPROVAL_REQUIRED: "ការបញ្ចុះតម្លៃលើសកំណត់ ត្រូវការការអនុម័ត",
    ErrorCode.OUT_OF_STOCK: "ស្តុកមិនគ្រប់គ្រាន់",
    ErrorCode.BATCH_EXPIRED: "ឡូតនេះផុតកំណត់",
    ErrorCode.BATCH_BLOCKED: "ឡូតនេះត្រូវបានបិទ",
    ErrorCode.BELOW_COST: "លក់ក្រោមថ្លៃដើម",
    ErrorCode.CREDIT_LIMIT_EXCEEDED: "លើសដែនកំណត់ឥណទាន",
    ErrorCode.RX_EXPIRED: "វេជ្ជបញ្ជាផុតសុពលភាព",
    ErrorCode.RX_QUANTITY_EXCEEDED: "បរិមាណលើសពីវេជ្ជបញ្ជា",
    ErrorCode.PRESCRIPTION_STATE: "វេជ្ជបញ្ជានេះមិនអាចប្រើបាន",
    ErrorCode.ALLERGY_WARNING: "ការព្រមាន៖ អាឡែស៊ី",
    ErrorCode.DUPLICATE_THERAPY_WARNING: "ការព្រមាន៖ ការព្យាបាលស្ទួន",
}  # fmt: skip


@dataclass
class Finding:
    code: str
    severity: str  # hard_stop | requirement | warning | info
    line_no: int | None
    message_en: str
    message_km: str
    details: dict[str, Any] = field(default_factory=dict)
    resolved: bool = False

    def out(self) -> dict[str, Any]:
        return dict(self.__dict__)


class Checks:
    def __init__(self, mode: Mode) -> None:
        self.mode = mode
        self.findings: list[Finding] = []

    def add(self, code: ErrorCode, message: str, *, status: int, line_no: int | None = None,
            details: dict[str, Any] | None = None, severity: str = "hard_stop", resolved: bool = False,
            message_km: str | None = None) -> None:  # fmt: skip
        if self.mode == "raise" and severity in ("hard_stop", "requirement") and not resolved:
            raise AppError(code, message, status_code=status, details=details or {})
        prefix = f"ជួរ {line_no}៖ " if line_no else ""
        self.findings.append(Finding(code.value, severity, line_no, message, message_km or prefix + KM.get(code, ""),
                                     details or {}, resolved))  # fmt: skip

    def error(self, err: AppError, line_no: int | None = None, severity: str | None = None) -> None:
        """A finding from another service's AppError (the read-only twins)."""
        sev = severity or ("warning" if err.code in WARNINGS else "hard_stop")
        self.findings.append(Finding(err.code.value, sev, line_no, err.message,
                                     err.message if " · " in err.message else KM.get(err.code, ""), err.details))  # fmt: skip

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in ("hard_stop", "warning") and not f.resolved]


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
    controlled: bool = False
    patient_id_document: str | None = None
    promo_discount: Decimal = Decimal("0.00")
    promotion_ids: list[str] = field(default_factory=list)
    manual_discount: Decimal = Decimal("0.00")
    order_line: Any = None
    promotion_amounts: dict[str, Decimal] = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        return self.line_total - self.promo_discount - self.manual_discount


@dataclass
class CheckResult:
    branch: Any
    customer: KnownCustomer | None
    lines: list[LinePlan]
    pharmacist: Any = None
    approver: UUID | None = None
    settlement: Any = None
    rate: Any = None
    subtotal: Decimal = Decimal("0.00")
    discount: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    checks: Checks | None = None
    khqr: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------- lines


async def plan_lines(session: AsyncSession, actor: CurrentUser, raw: list[dict[str, Any]], c: Checks) -> list[LinePlan]:
    plans = []
    for i, item in enumerate(raw, start=1):
        pack = (
            await session.execute(select(ProductPackUnit).where(ProductPackUnit.id == item["pack_unit_id"]))
        ).scalar_one_or_none()
        details = {"line": i}
        if pack is None or pack.product_id != item["medicine_id"]:
            c.add(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: unknown medicine or pack unit", status=422, line_no=i,
                  details=details)  # fmt: skip
            continue
        product = pack.product
        if not (pack.is_active and product.is_active):
            c.add(ErrorCode.UNKNOWN_MEDICINE, f"Line {i}: {product.sku} ({pack.name}) is not sold any more",
                  status=422, line_no=i, details=details)  # fmt: skip
            continue
        rx_item_id = item.get("rx_item_id")
        controlled = bool(product.controlled_schedule)
        if controlled:
            if rx_item_id is None:
                c.add(ErrorCode.RX_REQUIRED, f"Line {i}: {product.display_name} is a controlled medicine "
                      f"(schedule {product.controlled_schedule}): choose the patient's prescription",
                      status=422, line_no=i, details={**details, "medicine_id": str(product.id)})  # fmt: skip
            if not (actor.is_pharmacist and actor.has("controlled.dispense")):
                c.add(ErrorCode.PHARMACIST_REQUIRED, f"Line {i}: only a pharmacist allowed to dispense controlled "
                      "medicines", status=403, line_no=i, details=details)  # fmt: skip
            if not clean(item.get("patient_id_document")):
                c.add(ErrorCode.VALIDATION_ERROR, f"Line {i}: give the patient's ID card or passport number",
                      status=422, line_no=i, details={**details, "field": "patient_id_document"},
                      severity="requirement", message_km=f"ជួរ {i}៖ ត្រូវការលេខអត្តសញ្ញាណប័ណ្ណ ឬលិខិតឆ្លងដែនរបស់អ្នកជំងឺ")  # fmt: skip
        if product.is_rx_only and rx_item_id is None and not controlled:
            c.add(ErrorCode.RX_REQUIRED, f"Line {i}: {product.display_name} is prescription-only: choose the "
                  "patient's prescription", status=422, line_no=i, details={**details, "medicine_id": str(product.id)})  # fmt: skip
        allergy_reason = clean(item.get("allergy_override_reason")) or None
        if rx_item_id is not None and not (actor.is_pharmacist and actor.has("pos.dispense_rx")):
            c.add(ErrorCode.PHARMACIST_REQUIRED, f"Line {i}: only a pharmacist may dispense a prescription",
                  status=403, line_no=i, details=details)  # fmt: skip
        if allergy_reason and not (actor.is_pharmacist and actor.has("prescriptions.override_warning")):
            c.add(ErrorCode.PHARMACIST_REQUIRED, f"Line {i}: only a pharmacist allowed to override warnings may sell "
                  "despite an allergy", status=403, line_no=i, details=details)  # fmt: skip
        if allergy_reason and rx_item_id is None:
            c.add(ErrorCode.VALIDATION_ERROR, f"Line {i}: an allergy override needs the prescription", status=422,
                  line_no=i, details=details)  # fmt: skip
        batch_id = item.get("batch_id")
        reason = clean(item.get("override_reason")) or None
        if batch_id is not None:
            if not actor.is_pharmacist:
                c.add(ErrorCode.PHARMACIST_REQUIRED, f"Line {i}: only a pharmacist may choose the batch", status=403,
                      line_no=i, details=details)  # fmt: skip
            if not reason:
                c.add(ErrorCode.VALIDATION_ERROR, f"Line {i}: give the reason for choosing this batch", status=422,
                      line_no=i, details={**details, "field": "override_reason"})  # fmt: skip
        price = pack.sell_price
        plans.append(LinePlan(line_no=i, pack=pack, qty=item["qty"], qty_base=item["qty"] * pack.qty_in_base,
                              unit_price=price, line_total=money.usd(price * item["qty"]), batch_id=batch_id,
                              override_reason=reason, rx_item_id=rx_item_id, allergy_override_reason=allergy_reason,
                              acknowledge_warnings=bool(item.get("acknowledge_warnings")), controlled=controlled,
                              patient_id_document=clean(item.get("patient_id_document")) or None))  # fmt: skip
    return plans


async def customer_of(session: AsyncSession, customer_id: UUID | None, c: Checks) -> KnownCustomer | None:
    if customer_id is None:
        return None
    customer = await session.get(KnownCustomer, customer_id)
    if customer is None or not customer.is_active:
        c.add(ErrorCode.CUSTOMER_REQUIRED, "Unknown or deactivated customer", status=422)
        return None
    return customer


# ---------------------------------------------------------------- prices


async def price(session: AsyncSession, actor: CurrentUser, clients: Clients, branch_id: UUID, customer: Any,
                lines: list[LinePlan], data: dict[str, Any], order: Any, c: Checks,
                draft: Any = None) -> UUID | None:  # fmt: skip
    """Promotions (best deal; an order keeps its quoted prices), manual discounts and
    their approval. Returns who approved a discount above the seller's cap (raise mode)."""
    raw = {i: item for i, item in enumerate(data["lines"], start=1)}
    order_lines = {ol.id: ol for ol in order.lines} if order is not None else {}
    priced = []
    for x in lines:
        ol = order_lines.get(raw[x.line_no].get("order_line_id"))
        p = cart.PricedLine(x.line_no, x.pack, x.qty, x.unit_price, x.line_total)
        if ol is not None:
            x.order_line = ol
            p.unit_price, p.line_total = ol.unit_price, money.usd(ol.unit_price * x.qty)
            p.promo_discount = money.usd(ol.promo_discount * x.qty / ol.qty)
            p.promotion_ids = list(ol.promotion_ids)
        priced.append(p)
    await cart.apply_promotions(session, branch_id, customer, [p for p, x in zip(priced, lines, strict=True)
                                                              if x.order_line is None], draft=draft)  # fmt: skip
    cart.apply_manual(priced, [raw[x.line_no] for x in lines])
    approver = None
    if c.mode == "raise":
        approver = await cart.approve_discount(session, actor, clients.auth, branch_id, priced,
                                               data.get("discount_approval_token"))  # fmt: skip
    else:
        settings = await session.get(BranchSettingsCopy, branch_id)
        caps = settings.max_discount_pct if settings and settings.max_discount_pct else cart.DEFAULT_CAPS
        worst = cart.over_cap(caps, actor.role, priced)
        if worst is not None:
            roles = ["owner"] if actor.role == "branch_manager" else ["branch_manager", "owner"]
            c.add(ErrorCode.DISCOUNT_APPROVAL_REQUIRED, f"A {worst} % discount is above your cap of "
                  f"{caps.get(actor.role, 0)} %: {'the owner' if roles == ['owner'] else 'a manager'} confirms with "
                  "their PIN", status=403, severity="requirement", resolved=bool(data.get("discount_approval_token")),
                  details={"cap": caps.get(actor.role, 0), "asked": str(worst), "approver_roles": roles})  # fmt: skip
    for x, p in zip(lines, priced, strict=True):
        x.unit_price, x.line_total = p.unit_price, p.line_total
        x.promo_discount, x.promotion_ids, x.manual_discount = p.promo_discount, p.promotion_ids, p.manual_discount
        x.promotion_amounts = p.promotion_amounts
    return approver


# ---------------------------------------------------------------- step 1 of the saga


async def run_checks(session: AsyncSession, actor: CurrentUser, clients: Clients, data: dict[str, Any],
                     mode: Mode, *, order: Any = None, draft: Any = None) -> CheckResult:  # fmt: skip
    c = Checks(mode)
    branch = await branch_for(session, actor, data["branch_id"])
    customer = await customer_of(session, data.get("customer_id"), c)
    lines = await plan_lines(session, actor, data["lines"], c)
    pharmacist = None
    if any(x.controlled for x in lines):  # the PIN typed for this sale; one-time
        if mode == "raise":
            pharmacist = await consume_pin(clients.auth, data.get("pin_token"), "controlled.dispense", user=actor,
                                           branch_id=branch.id)  # fmt: skip
        else:
            c.add(ErrorCode.PIN_REQUIRED, "The pharmacist confirms controlled medicines with their PIN", status=401,
                  severity="requirement", resolved=bool(data.get("pin_token")))  # fmt: skip
    approver = await price(session, actor, clients, branch.id, customer, lines, data, order, c, draft)
    subtotal = sum((x.line_total for x in lines), Decimal("0.00"))
    discount = sum((x.promo_discount + x.manual_discount for x in lines), Decimal("0.00"))
    total = subtotal - discount
    rate = await rates.current(session, branch.id)
    result = CheckResult(branch, customer, lines, pharmacist, approver, None, rate, subtotal, discount, total, c)
    raw_payments = data.get("payments")
    if raw_payments is None:  # the preview without payments
        return result
    payments = [money.PaymentIn(p["method"], p["currency"], Decimal(str(p["amount"]))) for p in raw_payments]
    if any(p.method in ("credit", "deposit") for p in payments) and customer is None:
        c.add(ErrorCode.CUSTOMER_REQUIRED, "Choose the customer for a credit or deposit payment", status=422)
    if any(p["method"] == "deposit" and not p.get("deposit_id") for p in raw_payments):
        c.add(ErrorCode.VALIDATION_ERROR, "Say which deposit pays (deposit_id)", status=422)
    try:
        result.settlement = money.settle(total, payments, rate.khr_per_usd if rate else None,
                                         data.get("change_in") or "USD_KHR")  # fmt: skip
    except AppError as err:
        if mode == "raise":
            raise
        c.error(err)
    for raw in raw_payments:  # a KHQR paid for this sale: checked (and locked when posting)
        if raw.get("khqr_id") is None:
            continue
        if raw["method"] != "KHQR":
            c.add(ErrorCode.VALIDATION_ERROR, "khqr_id goes with method KHQR", status=422)
            continue
        try:
            result.khqr.append(await khqr.check_for_sale(session, actor, branch.id, raw["khqr_id"], raw["currency"],
                                                         Decimal(str(raw["amount"])), lock=mode == "raise"))  # fmt: skip
        except AppError as err:
            if mode == "raise":
                raise
            c.error(err)
    return result


# ---------------------------------------------------------------- after the reservation


def below_cost(actor: CurrentUser, lines: list[LinePlan], reservation: dict[str, Any], c: Checks) -> list[str]:
    """Cost known per batch: no line may sell below cost without sales.below_cost
    (BELOW_COST; the saga undoes the reservation)."""
    cost: dict[int, Decimal] = {}
    for r in reservation["lines"]:
        cost[r["line_no"]] = cost.get(r["line_no"], Decimal("0")) + Decimal(str(r["cost_per_base"])) * r["qty_base"]
    below = [x for x in lines if x.net < cost.get(x.line_no, Decimal("0")).quantize(Decimal("0.01"))]
    if below and not actor.has("sales.below_cost"):
        if c.mode == "raise":
            x = below[0]
            raise AppError(ErrorCode.BELOW_COST, f"Line {x.line_no}: {x.pack.product.sku} would sell below cost",
                           status_code=422, details={"lines": [b.line_no for b in below]})  # fmt: skip
        for x in below:
            c.add(ErrorCode.BELOW_COST, f"Line {x.line_no}: {x.pack.product.sku} would sell below cost", status=422,
                  line_no=x.line_no, details={"lines": [x.line_no]})  # fmt: skip
    return [f"line {x.line_no}: {x.pack.product.sku} net {x.net} below cost" for x in below]


# ---------------------------------------------------------------- the preview's read-only twins


async def preview_rx(clients: Clients, actor: CurrentUser, branch_id: UUID, lines: list[LinePlan],
                     c: Checks) -> dict[int, dict]:  # fmt: skip
    rx_lines = [x for x in lines if x.rx_item_id]
    if not rx_lines:
        return {}
    try:
        out = await clients.prescription.post("/rx/check", {"branch_id": str(branch_id), "lines": [
            {"line_no": x.line_no, "rx_item_id": str(x.rx_item_id), "medicine_id": str(x.pack.product_id),
             "qty_base": x.qty_base, "allergy_override_reason": x.allergy_override_reason,
             "acknowledge_warnings": x.acknowledge_warnings} for x in rx_lines]}, actor=actor, branch_id=branch_id)  # fmt: skip
    except AppError as err:
        if err.code in WARNINGS:
            for b in err.details.get("lines") or [{}]:
                c.error(AppError(err.code, " / ".join(f"{w['en']} · {w['km']}" for w in b.get("warnings", [])) or
                                 err.message, details=b), b.get("line_no"))  # fmt: skip
        else:
            c.error(err, err.details.get("line_no"))
        return {}
    held = {x["line_no"]: x for x in out["lines"]}
    for n, h in held.items():
        for w in h.get("warnings") or []:
            code = ErrorCode.ALLERGY_WARNING if w["kind"] == "allergy" else ErrorCode.DUPLICATE_THERAPY_WARNING
            c.add(code, w["en"], status=409, line_no=n, severity="warning", resolved=True, message_km=w["km"],
                  details={"warning": w})  # fmt: skip
    return held


async def preview_stock(clients: Clients, actor: CurrentUser, branch_id: UUID, lines: list[LinePlan],
                        c: Checks) -> dict[int, list[dict]]:  # fmt: skip
    if not lines:
        return {}
    try:
        planned = await clients.inventory.post("/reservations/plan", {"branch_id": str(branch_id), "lines": [
            {"line_no": x.line_no, "medicine_id": str(x.pack.product_id), "qty_base": x.qty_base,
             **({"batch_id": str(x.batch_id)} if x.batch_id else {})} for x in lines]},
            actor=actor, branch_id=branch_id)  # fmt: skip
    except AppError as err:
        if err.code == ErrorCode.OUT_OF_STOCK and err.details.get("lines"):
            for m in err.details["lines"]:
                c.error(AppError(err.code, f"Line {m['line_no']}: only {m['available']} of {m['requested']} can be "
                                 "sold here now", details=m), m["line_no"])  # fmt: skip
        else:
            c.error(err, err.details.get("line_no"))
        return {}
    below_cost(actor, lines, planned, c)
    soon = clock.today().toordinal() + 30
    by_line: dict[int, list[dict]] = {}
    for b in planned["lines"]:
        by_line.setdefault(b["line_no"], []).append(b)
        expiry = b["expiry_date"]
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)
        if expiry.toordinal() <= soon:
            c.findings.append(Finding("NEAR_EXPIRY", "info", b["line_no"], f"Line {b['line_no']}: lot {b['lot_no']} "
                                      f"expires on {expiry}", f"ជួរ {b['line_no']}៖ ឡូត {b['lot_no']} ជិតផុតកំណត់",
                                      {"lot_no": b["lot_no"], "expiry_date": str(expiry)}))  # fmt: skip
    return by_line


async def preview_credit(clients: Clients, actor: CurrentUser, result: CheckResult, c: Checks) -> None:
    s = result.settlement
    if s is None or s.credit <= 0 or result.customer is None:
        return
    status = await clients.customers.get(f"/customers/{result.customer.id}/credit", actor=actor,
                                         branch_id=result.branch.id)  # fmt: skip
    available = Decimal(str(status["available"]))
    if s.credit > available:
        c.add(ErrorCode.CREDIT_LIMIT_EXCEEDED, f"{result.customer.name} can take {available} USD more on credit "
              f"(limit {status['credit_limit']})", status=422,
              details={"credit_limit": str(status["credit_limit"]), "balance": str(status["balance"]),
                       "amount": str(s.credit), "available": str(available)})  # fmt: skip
