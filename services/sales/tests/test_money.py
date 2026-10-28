from decimal import Decimal

import pytest

from pharmacy_shared.errors import AppError
from sales_service.services.money import PaymentIn, round_riel, settle

D = Decimal


def cash(amount: str, currency: str = "USD") -> PaymentIn:
    return PaymentIn("cash", currency, D(amount))


@pytest.mark.parametrize(
    ("riel", "rounded"), [("149.99", 100), ("150", 200), ("2050", 2100), ("2049", 2000), ("0", 0)]
)
def test_riel_rounds_to_the_nearest_100_half_up(riel, rounded) -> None:
    assert round_riel(D(riel)) == rounded


def test_mixed_usd_and_khr_cash_with_change_in_dollars_and_riel() -> None:
    # total 7.35; customer gives $5 + 12,000 riel (= 2.93 at 4100) → 7.93 paid, 0.58 change
    s = settle(D("7.35"), [cash("5.00"), cash("12000", "KHR")], 4100, "USD_KHR")
    assert [u for _, u in s.payments] == [D("5.00"), D("2.93")]
    assert (s.paid, s.change_usd, s.change_given_usd, s.change_given_khr) == (
        D("7.93"),
        D("0.58"),
        D("0.00"),
        2400,
    )
    assert s.change_rounding_khr == D("-22.00")  # exact 2,378 riel, 2,400 handed over
    assert s.total_khr == 30100  # 7.35 × 4100 = 30,135 → 30,100


def test_change_in_usd_khr_gives_whole_dollars_and_the_cents_in_riel() -> None:
    s = settle(D("6.25"), [cash("10.00")], 4100, "USD_KHR")
    assert (s.change_usd, s.change_given_usd, s.change_given_khr) == (D("3.75"), D("3.00"), 3100)
    assert s.change_rounding_khr == D("-25.00")  # 0.75 × 4100 = 3,075 → 3,100


def test_change_all_in_riel_or_all_in_dollars() -> None:
    assert settle(D("6.25"), [cash("10.00")], 4000, "KHR").change_given_khr == 15000
    s = settle(D("6.25"), [cash("10.00")], None, "USD")
    assert (s.change_given_usd, s.change_given_khr, s.total_khr) == (D("3.75"), 0, None)


def test_short_payment_is_refused() -> None:
    with pytest.raises(AppError) as exc:
        settle(D("10.00"), [cash("9.99")], 4100, "USD")
    assert exc.value.code == "PAYMENT_SHORT" and exc.value.details["missing"] == "0.01"


def test_card_and_credit_cannot_overpay() -> None:
    with pytest.raises(AppError):
        settle(D("10.00"), [PaymentIn("card", "USD", D("12.00"))], 4100, "USD")
    s = settle(D("10.00"), [PaymentIn("credit", "USD", D("4.00")), cash("10.00")], 4100, "USD")
    assert (s.credit, s.paid, s.change_usd) == (D("4.00"), D("10.00"), D("4.00"))


def test_riel_needs_a_rate_and_whole_hundreds() -> None:
    with pytest.raises(AppError) as exc:
        settle(D("1.00"), [cash("4100", "KHR")], None, "USD")
    assert exc.value.code == "EXCHANGE_RATE_MISSING"
    with pytest.raises(AppError):
        settle(D("1.00"), [cash("4150", "KHR")], 4100, "USD")
