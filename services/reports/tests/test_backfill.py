"""Backfill: replaying the services' outboxes rebuilds the read models; running
it twice (or after live events with the same ids) changes nothing."""

from uuid import UUID, uuid4

from sqlalchemy import func, select

from reports_service.config import get_settings
from reports_service.db import db
from reports_service.models import Invoice, InvoiceLine, Movement, Payment, ReplayCursor, SalesDaily, StockRow
from reports_service.services.backfill import backfill

from .conftest import PP1, event, invoice, line


class Outbox:
    """Stands in for GET /internal/v1/outbox of one service."""

    def __init__(self, events: list[tuple[str, dict]]) -> None:
        self.items = [{"id": str(uuid4()), "seq": i + 1, "event_type": t, "payload": p,
                       "created_at": "2026-10-27T03:00:00+00:00"} for i, (t, p) in enumerate(events)]  # fmt: skip
        self.calls = 0

    async def get(self, path: str, params: dict) -> dict:
        assert path == "/outbox"
        self.calls += 1
        page = [x for x in self.items if x["seq"] > params["after_seq"]][: params["limit"]]
        return {"items": page, "next_after_seq": page[-1]["seq"] if page else params["after_seq"],
                "more": len(page) == params["limit"]}  # fmt: skip


async def snapshot() -> tuple:
    async with db.sessionmaker() as s:
        return tuple([(await s.execute(select(func.count()).select_from(m))).scalar_one()
                      for m in (Invoice, InvoiceLine, Payment, Movement, StockRow, SalesDaily)]
                     + [(await s.execute(select(func.sum(SalesDaily.net)))).scalar_one()])  # fmt: skip


async def test_backfill_twice_gives_the_same_tables() -> None:
    para = uuid4()
    batch = uuid4()
    catalog = Outbox([("medicine.created", {
        "medicine_id": str(para), "version": 1, "sku": "PARA500", "brand_name": "Para", "generic_name": "P",
        "base_unit": "tablet", "is_rx_only": False, "controlled_schedule": None, "is_active": True,
        "pack_units": []})])  # fmt: skip
    sales = Outbox([("invoice.created", invoice(f"PP1-INV-{n}", [line(para, 10, "1.00", "0.40")])) for n in range(5)]
                   + [("cart.suspended", {"x": 1})])  # not a report event: skipped
    inventory = Outbox([("stock.changed", {
        "movement_id": str(uuid4()), "seq": n, "branch_id": str(PP1), "batch_id": str(batch), "medicine_id": str(para),
        "type": "in" if n == 1 else "out", "delta": 100 if n == 1 else -10, "qty_after": 100 - 10 * (n - 1),
        "lot_no": "A", "expiry_date": "2028-01-31", "cost_per_base": "0.0400",
        "occurred_at": "2026-10-27T03:00:00+00:00"}) for n in range(1, 7)])  # fmt: skip
    sources = {"catalog": catalog, "sales": sales, "inventory": inventory}
    settings = get_settings().model_copy(update={"replay_page_size": 2})
    first = await backfill(db, settings, list(sources), clients=sources)
    assert first["sales"] == {"read": 6, "applied": 5} and first["inventory"]["applied"] == 6
    after_first = await snapshot()
    assert after_first[:6] == (5, 5, 5, 6, 1, 5)  # 5 cashiers: 5 rollup rows
    assert str(after_first[-1]) == "5.00"
    again = await backfill(db, settings, list(sources), clients=sources)
    assert again["sales"] == {"read": 0, "applied": 0}  # the cursor remembers where it was
    async with db.sessionmaker() as s:
        await s.execute(ReplayCursor.__table__.delete())
        await s.commit()
    from_zero = await backfill(db, settings, list(sources), clients=sources)
    assert from_zero["sales"] == {"read": 6, "applied": 0}  # every event seen already
    assert await snapshot() == after_first
    rebuilt = await backfill(db, settings, list(sources), rebuild=True, clients=sources)
    assert rebuilt["sales"]["applied"] == 5 and await snapshot() == after_first
    async with db.sessionmaker() as s:
        assert (await s.get(StockRow, (PP1, batch))).qty_on_hand == 50


async def test_a_live_event_and_its_replay_count_once() -> None:
    para = uuid4()
    payload = invoice("PP1-INV-1", [line(para, 10, "1.00", "0.40")])
    sales = Outbox([("invoice.created", payload)])
    await event("invoice.created", payload, message_id=UUID(sales.items[0]["id"]))  # live
    done = await backfill(db, get_settings(), ["sales"], clients={"sales": sales})
    assert done["sales"] == {"read": 1, "applied": 0}
    assert (await snapshot())[0] == 1
