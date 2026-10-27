from decimal import Decimal

import pytest

from pharmacy_shared.spreadsheet import safe_cell


@pytest.mark.parametrize(
    "value", ["=1+1", "+855 12 345 678", "-2+3", "@SUM(A1)", '=HYPERLINK("http://x")', "\t=1"]
)
def test_formula_like_text_is_escaped(value) -> None:
    assert safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["Paracetamol 500mg", "ប៉ារ៉ាសេតាម៉ុល", "", None, -5, 1.5, Decimal("-1.20")])
def test_other_values_are_unchanged(value) -> None:
    assert safe_cell(value) == value
