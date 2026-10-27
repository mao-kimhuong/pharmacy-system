import asyncio
from datetime import date, datetime

from sqlalchemy import text

from inventory_service.db import db
from inventory_service.services.expiry import ADVISORY_LOCK_KEY, expire_batches, next_run
from pharmacy_shared import clock

from .conftest import CASHIER, OWNER, PREFIX, add_product, event, goods_received, outbox, scalar, stock_of


async def run(today: date, **kw):
    async with db.sessionmaker() as session:
        return await expire_batches(session, today, **kw)


async def test_past_expiry_batches_become_expired_with_event_and_log(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("OLD", "2026-11-30", 10, "0.04"),
                                                        ("NEW", "2028-03-31", 10, "0.04")]))  # fmt: skip
    assert await run(date(2026, 11, 30)) == []  # usable through its expiry date
    done = await run(date(2026, 12, 1))
    assert [d["lot_no"] for d in done] == ["OLD"] and done[0]["branches"][0]["qty_on_hand"] == 10
    batches = (await client.get(f"{PREFIX}/batches", headers=OWNER)).json()["items"]
    assert {b["lot_no"]: (b["status"], b["qty_available"]) for b in batches} == {
        "OLD": ("expired", 0), "NEW": ("active", 10),
    }  # fmt: skip
    expired = [p for t, p in await outbox() if t == "batch.expired"]
    assert len(expired) == 1 and expired[0]["lot_no"] == "OLD"
    audit = [p for t, p in await outbox() if t == "audit.recorded"][-1]
    assert audit["action"] == "batch.expired" and audit["actor_id"] is None
    assert await run(date(2026, 12, 2)) == []  # already expired: not again
    [item] = await stock_of(client, headers=CASHIER)
    assert item["qty_on_hand"] == 20 and item["qty_available"] == 10


async def test_dry_run_changes_nothing(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("OLD", "2026-11-30", 10, "0.04")]))
    assert len(await run(date(2027, 1, 1), dry_run=True)) == 1
    assert await scalar("SELECT count(*) FROM batches WHERE status = 'expired'") == 0
    assert not [t for t, _ in await outbox() if t == "batch.expired"]


async def test_only_one_replica_runs_it(client) -> None:
    para = await add_product()
    await event("goods.received", goods_received(para, [("OLD", "2026-11-30", 10, "0.04")]))
    async with db.engine.connect() as other:
        await other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
        assert await run(date(2027, 1, 1)) is None
        await other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
    assert len(await run(date(2027, 1, 1))) == 1


def test_next_run_is_0005_phnom_penh() -> None:
    tz = clock.TIMEZONE
    assert next_run(datetime(2026, 10, 27, 0, 4, tzinfo=tz), 0, 5) == datetime(2026, 10, 27, 0, 5, tzinfo=tz)
    assert next_run(datetime(2026, 10, 27, 0, 5, tzinfo=tz), 0, 5) == datetime(2026, 10, 28, 0, 5, tzinfo=tz)
    assert next_run(datetime(2026, 10, 27, 15, 0, tzinfo=tz), 0, 5) == datetime(2026, 10, 28, 0, 5, tzinfo=tz)


async def test_scheduler_runs_at_start_and_stops(client, monkeypatch) -> None:
    from inventory_service.services import expiry

    para = await add_product()
    await event("goods.received", goods_received(para, [("OLD", "2026-10-20", 10, "0.04")]))
    stop = asyncio.Event()
    task = asyncio.create_task(expiry.run_scheduler(db, stop, 0, 5))
    for _ in range(50):
        if await scalar("SELECT count(*) FROM batches WHERE status = 'expired'"):
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 2)
    assert await scalar("SELECT count(*) FROM batches WHERE status = 'expired'") == 1
