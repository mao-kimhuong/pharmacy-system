"""USD / KHR arithmetic for the till. Rules:

- Prices and totals are USD, NUMERIC(14,2). The branch rate is whole riel per USD.
- Riel paid must be whole hundreds (the smallest note is 100 riel); it counts
  as riel / rate USD, rounded half up to the cent.
- Change comes only out of cash: card / ABA / KHQR and credit may not pay
  more than the total.
- Change is given as
    USD      all in dollars,
    KHR      all in riel, rounded to 100 riel (half up),
    USD_KHR  whole dollars in USD and the cents in riel (the usual way in Cambodia).
  The difference between the exact riel and the riel handed over is kept on the
  invoice (change_rounding_khr, + = the drawer keeps it), so the cash drawer
  reconciles to the riel.
- Riel is compared in riel: what the USD payments (and credit) leave is due in riel at the
  invoice's rate, rounded to 100 riel (for an all-riel sale: the invoice's total_khr). Riel
  paid = riel due settles it exactly, even when that riel is a few cents above or below in USD
  (2.70 USD at 4100 = 11 070 → 11 100 riel due; 2.62 → 10 742 → 10 700); the difference is kept
  on the invoice (payment_rounding_khr, + = the shop received more than the exact riel). Card /
  ABA / KHQR in riel may not pay more riel than is due; more riel in cash gives change as above.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from pharmacy_shared.errors import AppError, ErrorCode

CENT = Decimal("0.01")
NON_CASH = ("card", "ABA", "KHQR", "deposit")  # deposit: a sale order's, never gives change


def usd(value: Decimal | str | int) -> Decimal:
    return Decimal(str(value)).quantize(CENT, ROUND_HALF_UP)


def round_riel(value: Decimal) -> int:
    """To the nearest 100 riel, half up."""
    return int((value / 100).quantize(Decimal("1"), ROUND_HALF_UP) * 100)


def khr_to_usd(riel: Decimal, rate: int) -> Decimal:
    return usd(Decimal(riel) / rate)


@dataclass(frozen=True)
class PaymentIn:
    method: str  # cash card ABA KHQR credit
    currency: str  # USD KHR
    amount: Decimal


@dataclass(frozen=True)
class Settlement:
    payments: list[tuple[PaymentIn, Decimal]]  # with amount in USD
    paid: Decimal  # every payment except credit, USD
    credit: Decimal
    change_usd: Decimal  # change owed, USD
    change_given_usd: Decimal
    change_given_khr: int
    change_rounding_khr: Decimal
    total_khr: int | None
    payment_rounding_khr: Decimal = Decimal("0.00")  # riel due (rounded) − exact riel, when riel settled it exactly


def settle(total: Decimal, payments: list[PaymentIn], rate: int | None, change_in: str) -> Settlement:
    needs_rate = any(p.currency == "KHR" for p in payments)
    if needs_rate and rate is None:
        raise AppError(ErrorCode.EXCHANGE_RATE_MISSING, "Set the branch's KHR exchange rate before taking riel",
                       status_code=422)  # fmt: skip
    converted = []
    for i, p in enumerate(payments, start=1):
        if p.currency == "KHR":
            if p.method == "credit":
                raise AppError(
                    ErrorCode.VALIDATION_ERROR, "Credit is in USD", status_code=422, details={"payment": i}
                )
            if p.amount != p.amount.to_integral_value() or int(p.amount) % 100:
                raise AppError(ErrorCode.VALIDATION_ERROR, f"Payment {i}: riel must be whole hundreds",
                               status_code=422, details={"payment": i})  # fmt: skip
            converted.append((p, khr_to_usd(p.amount, rate)))
        else:
            converted.append((p, usd(p.amount)))
    payment_rounding = Decimal("0.00")
    if needs_rate:
        # compare riel with riel: what the USD payments leave is due in riel, rounded to 100 at this rate
        usd_part = sum((u for p, u in converted if p.currency == "USD"), Decimal("0.00"))
        left_usd = max(total - usd_part, Decimal("0.00"))
        due_khr = round_riel(left_usd * rate)
        khr_paid = sum((int(p.amount) for p, _ in converted if p.currency == "KHR"), 0)
        khr_non_cash = sum((int(p.amount) for p, _ in converted if p.currency == "KHR" and p.method in NON_CASH), 0)
        if khr_non_cash > due_khr:
            raise AppError(ErrorCode.VALIDATION_ERROR, f"Card, ABA and KHQR in riel cannot pay more than the {due_khr} "
                           "riel due; change is given only from cash", status_code=422,
                           details={"due_khr": due_khr})  # fmt: skip
        if khr_paid < due_khr:
            missing = due_khr - khr_paid
            raise AppError(ErrorCode.PAYMENT_SHORT, f"{missing} riel still to pay", status_code=422,
                           details={"total": str(total), "due_khr": due_khr, "missing_khr": missing,
                                    "missing": str(khr_to_usd(Decimal(missing), rate))})  # fmt: skip
        if khr_paid == due_khr and left_usd > 0:  # settled exactly in riel: the riel part is worth what was left
            payment_rounding = (Decimal(due_khr) - left_usd * rate).quantize(CENT)
            khr_rows = [i for i, (p, _) in enumerate(converted) if p.currency == "KHR"]
            given = Decimal("0.00")
            for n, i in enumerate(khr_rows):
                p, _ = converted[i]
                share = left_usd - given if n == len(khr_rows) - 1 else usd(left_usd * int(p.amount) / due_khr)
                given += share
                converted[i] = (p, share)
    credit = sum((u for p, u in converted if p.method == "credit"), Decimal("0.00"))
    cash = sum((u for p, u in converted if p.method == "cash"), Decimal("0.00"))
    non_cash = sum((u for p, u in converted if p.method in NON_CASH), Decimal("0.00"))
    paid = cash + non_cash
    usd_non_cash = sum((u for p, u in converted if p.method in NON_CASH and p.currency == "USD"), Decimal("0.00"))
    if usd_non_cash + credit > total or (non_cash + credit > total and not needs_rate):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Card, ABA, KHQR and credit cannot pay more than the total; "
                       "change is given only from cash", status_code=422)  # fmt: skip
    if paid + credit < total:
        raise AppError(ErrorCode.PAYMENT_SHORT, f"{usd(total - paid - credit)} USD still to pay", status_code=422,
                       details={"total": str(total), "paid": str(paid + credit),
                                "missing": str(usd(total - paid - credit))})  # fmt: skip
    change = paid + credit - total
    given_usd, given_khr, rounding = change, 0, Decimal("0.00")
    if change > 0 and change_in != "USD":
        if rate is None:
            raise AppError(ErrorCode.EXCHANGE_RATE_MISSING, "Set the KHR rate to give change in riel, or give "
                           "change in USD", status_code=422)  # fmt: skip
        given_usd = change.quantize(Decimal("1"), ROUND_DOWN) if change_in == "USD_KHR" else Decimal("0.00")
        exact_riel = (change - given_usd) * rate
        given_khr = round_riel(exact_riel)
        rounding = (exact_riel - given_khr).quantize(CENT)
        given_usd = usd(given_usd)
    total_khr = round_riel(total * rate) if rate else None
    return Settlement(converted, paid, credit, usd(change), given_usd, given_khr, rounding, total_khr, payment_rounding)
