"""T2: days of supply of a dispensed Rx line → rx.supply (refill reminders in the notification service)."""

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from prescription_service.db import db
from prescription_service.models import OutboxEvent, RxItem
from prescription_service.services.supply import supply_days

from .conftest import (
    PHARMACIST,
    PREFIX,
    add_doctor,
    add_patient,
    add_product,
    add_rx,
    event,
    hold,
    invoice_event,
)


def item(**kw) -> RxItem:  # noqa: ANN003
    return RxItem(qty_base=kw.pop("qty_base", 30), dispensed_base=0, held_base=0, repeats_allowed=0, **kw)


def test_supply_days_from_the_dose_else_the_duration_else_none() -> None:
    assert supply_days(item(units_per_dose=Decimal("1"), doses_per_day=Decimal("3")), 21) == 7
    assert supply_days(item(units_per_dose=Decimal("2"), doses_per_day=Decimal("3")), 20) == 3  # rounded down
    assert supply_days(item(units_per_dose=Decimal("1"), doses_per_day=Decimal("0.5")), 10) == 20  # every other day
    assert supply_days(item(qty_base=30, duration_days=30), 15) == 15  # half a fill: half the days
    assert supply_days(item(frequency="3 times a day"), 21) is None  # free text is never guessed
    assert supply_days(item(duration_days=10), 0) == 0


async def supplies() -> list[dict]:
    async with db.sessionmaker() as s:
        rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.event_type == "rx.supply")
                                .order_by(OutboxEvent.created_at))).scalars()  # fmt: skip
        return [r.payload for r in rows]


async def test_dispensing_sends_the_supply_and_a_cancel_sends_zero(client) -> None:
    p, d, m = await add_patient(client), await add_doctor(client), await add_product()
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 21, "repeats_allowed": 1, "dosage": "1 tablet",
                                      "frequency": "3x a day", "units_per_dose": "1", "doses_per_day": "3"}])  # fmt: skip
    assert rx["items"][0]["units_per_dose"] == "1.00" and rx["items"][0]["doses_per_day"] == "3.00"
    it, inv, customer = rx["items"][0]["id"], str(uuid4()), str(uuid4())
    assert (await hold(client, it, m, 21, invoice_id=inv)).status_code == 200
    sale = {**invoice_event(inv, [(1, it, 21, 0)]), "customer": {"id": customer},
            "completed_at": "2026-10-27T03:00:00+00:00"}  # fmt: skip
    sale["lines"][0]["name"] = "Amoxicillin 500"
    await event("invoice.created", sale)
    (s,) = await supplies()
    assert (s["supply_days"], s["runs_out_on"], s["dispensed_on"]) == (7, "2026-11-03", "2026-10-27")
    assert s["customer_id"] == customer and s["prescription_number"] == rx["number"] and s["refills_left"] is True
    assert "notes" not in s and "doctor" not in s and "patient" not in s  # nothing a chat must not see
    await event("invoice.cancelled", {**sale, "version": 2, "status": "cancelled"})
    assert (await supplies())[-1]["supply_days"] == 0 and (await supplies())[-1]["runs_out_on"] is None
    left = await client.get(f"{PREFIX}/prescriptions/{rx['id']}/remaining", headers=PHARMACIST)
    assert left.json()["items"][0]["remaining_base"] == 42


async def test_no_dose_and_no_duration_sends_nothing(client) -> None:
    p, d, m = await add_patient(client), await add_doctor(client), await add_product()
    rx = await add_rx(client, p, d, [{"medicine_id": m, "qty_base": 10, "frequency": "when needed"}])
    it, inv = rx["items"][0]["id"], str(uuid4())
    await hold(client, it, m, 10, invoice_id=inv)
    await event("invoice.created", {**invoice_event(inv, [(1, it, 10, 0)]), "customer": {"id": str(uuid4())}})
    assert await supplies() == []
