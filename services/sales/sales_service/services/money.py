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
    credit = sum((u for p, u in converted if p.method == "credit"), Decimal("0.00"))
    cash = sum((u for p, u in converted if p.method == "cash"), Decimal("0.00"))
    non_cash = sum((u for p, u in converted if p.method in NON_CASH), Decimal("0.00"))
    paid = cash + non_cash
    if non_cash + credit > total:
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
    return Settlement(converted, paid, credit, usd(change), given_usd, given_khr, rounding, total_khr)
