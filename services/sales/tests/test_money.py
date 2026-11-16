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


def khqr(amount: str, currency: str = "KHR") -> PaymentIn:
    return PaymentIn("KHQR", currency, D(amount))


@pytest.mark.parametrize("method", ["KHQR", "cash"])
def test_riel_that_rounds_up_settles_exactly(method) -> None:  # noqa: ANN001
    # 2.70 USD × 4100 = 11 070 riel → 11 100 due; 11 100 / 4100 = 2.71 USD was refused as overpaying
    s = settle(D("2.70"), [PaymentIn(method, "KHR", D("11100"))], 4100, "USD_KHR")
    assert s.total_khr == 11100 and s.paid == D("2.70") and s.change_usd == 0 and s.change_given_khr == 0
    assert s.payments[0][1] == D("2.70") and s.payment_rounding_khr == D("30.00")  # the shop got 30 riel more


@pytest.mark.parametrize("method", ["KHQR", "cash"])
def test_riel_that_rounds_down_settles_exactly(method) -> None:  # noqa: ANN001
    # 2.62 USD × 4100 = 10 742 riel → 10 700 due; 10 700 / 4100 = 2.61 USD was refused as short
    s = settle(D("2.62"), [PaymentIn(method, "KHR", D("10700"))], 4100, "USD_KHR")
    assert s.total_khr == 10700 and s.paid == D("2.62") and s.change_usd == 0
    assert s.payment_rounding_khr == D("-42.00")  # 42 riel less than the exact riel


def test_riel_is_compared_in_riel_short_and_over() -> None:
    with pytest.raises(AppError) as exc:
        settle(D("2.70"), [khqr("11000")], 4100, "USD")
    assert exc.value.code == "PAYMENT_SHORT" and exc.value.details["missing_khr"] == 100
    with pytest.raises(AppError) as exc:
        settle(D("2.70"), [khqr("11200")], 4100, "USD")  # a KHQR cannot give change
    assert exc.value.code == "VALIDATION_ERROR" and exc.value.details["due_khr"] == 11100
    s = settle(D("2.70"), [cash("12000", "KHR")], 4100, "KHR")  # cash in riel above what is due: change as before
    assert s.change_usd == D("0.23") and s.change_given_khr == 900 and s.payment_rounding_khr == 0


def test_usd_first_then_the_rest_due_in_riel() -> None:
    # 5.00 USD paid; 2.35 left × 4100 = 9 635 → 9 600 riel due by KHQR
    s = settle(D("7.35"), [cash("5.00"), khqr("9600")], 4100, "USD")
    assert s.paid == D("7.35") and [u for _, u in s.payments] == [D("5.00"), D("2.35")]
    assert s.payment_rounding_khr == D("-35.00")
    with pytest.raises(AppError):
        settle(D("7.35"), [cash("5.00"), khqr("9700")], 4100, "USD")
    two = settle(D("2.70"), [khqr("5000"), PaymentIn("ABA", "KHR", D("6100"))], 4100, "USD")  # riel split over two
    assert sum(u for _, u in two.payments) == D("2.70")
