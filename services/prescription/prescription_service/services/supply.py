"""Days of supply of a dispensed Rx line (T2 refill reminders).

- With a structured dose: qty dispensed ÷ (units per dose × doses per day), rounded down.
- Else with the Rx duration: duration_days × qty dispensed ÷ one fill (a part fill lasts that much less).
- Else (free-text frequency only): None. The text is never parsed: a wrong guess would remind on the wrong day.
"""

import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ..models import RxItem


def supply_days(item: RxItem, qty_base: int) -> int | None:
    if qty_base <= 0:
        return 0
    if item.units_per_dose and item.doses_per_day:
        per_day = Decimal(item.units_per_dose) * Decimal(item.doses_per_day)
        return max(1, math.floor(Decimal(qty_base) / per_day)) if per_day > 0 else None
    if item.duration_days:
        return max(1, item.duration_days * qty_base // item.qty_base)
    return None


def supply_event(item: RxItem, rx: Any, invoice: dict[str, Any], qty_base: int, dispensed_on: date,
                 medicine_name: str) -> dict[str, Any] | None:  # fmt: skip
    """The rx.supply payload for one invoice line (None: nothing can be worked out). qty 0 (cancelled or
    all returned) says "no supply from this invoice any more"."""
    days = supply_days(item, qty_base)
    if days is None:
        return None
    customer = invoice.get("customer") or {}
    return {
        "rx_item_id": str(item.id), "prescription_id": str(rx.id), "prescription_number": rx.number,
        "branch_id": str(rx.branch_id), "invoice_id": str(invoice["invoice_id"]),
        "invoice_version": int(invoice.get("version") or 0), "customer_id": customer.get("id"),
        "medicine_name": medicine_name, "qty_base": qty_base, "dispensed_on": dispensed_on.isoformat(),
        "supply_days": days, "runs_out_on": (dispensed_on + timedelta(days=days)).isoformat() if days else None,
        "refills_left": item.remaining_base > 0,
    }  # fmt: skip
