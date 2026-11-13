"""T2 phase 4: operations alerts – till heartbeat during opening hours, late opening, fridge sensors (out of range
for more than 10 minutes, back in range, silent), the 07:30 fridge lines, the first / last sale in the summary."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from notification_service.db import db
from notification_service.main import app
from notification_service.services import ops, texts
from notification_service.services.jobs import stock_digest
from pharmacy_shared import clock

from .conftest import PP1, PP2, PREFIX, event, messages, user

HOURS = {d: ["07:00", "21:00"] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
CASHIER = user("cashier", "pos.sell")
MANAGER = user("branch_manager", "notifications.manage")


def pp(hh: int, mm: int, day: int = 27) -> datetime:
    """A Phnom Penh time on 27 Oct 2026 (a Tuesday), as UTC."""
    return datetime(2026, 10, day, hh, mm, tzinfo=clock.TIMEZONE).astimezone(UTC)


async def job(at: datetime) -> int:
    async with db.sessionmaker() as s:
        return await ops.minute_job(s, app.state.settings, at) or 0


async def beat(client, at: datetime, monkeypatch, branch=PP1, device: str = "till-1") -> None:  # noqa: ANN001
    monkeypatch.setattr(clock, "now", lambda: at)
    r = await client.post(f"{PREFIX}/heartbeat", json={"branch_id": str(branch), "device_id": device}, headers=CASHIER)
    assert r.status_code == 200, r.text


async def ops_texts() -> list[tuple[str, str]]:
    return [(m.target, m.text) for m in await messages() if m.kind in ("ops", "sensor")]


async def offline_alerts() -> int:
    return len([1 for t, x in await ops_texts() if t == "owner" and "no till has been online" in x])


@pytest.fixture(autouse=True)
async def hours():  # noqa: ANN201
    await event("branch.settings_updated", {"branch_id": str(PP1), "refill_reminder_days": 3, "opening_hours": HOURS})


async def test_offline_only_during_opening_hours_after_10_minutes_and_back(client, monkeypatch) -> None:
    assert await job(pp(6, 50)) == 0  # closed
    assert await job(pp(7, 9)) == 0  # open 9 minutes: give the tills time
    assert await job(pp(7, 10)) == 1  # open 10 minutes, no till seen
    assert await job(pp(7, 15)) == 0  # once
    rows = await ops_texts()
    assert [t for t, _ in rows] == [str(PP1), "owner"]
    assert "no till has been online for 10 minutes. Check" in rows[0][1] and "គ្មានបញ្ជរ" in rows[0][1]
    await beat(client, pp(7, 20), monkeypatch)
    back = (await ops_texts())[-1][1]
    assert "the till is back online (offline 07:00–07:20)" in back
    await beat(client, pp(8, 0), monkeypatch, device="till-2")
    await job(pp(8, 9))  # (the late-opening alert goes now: no sale by 07:30)
    assert await offline_alerts() == 1  # 9 minutes since the last heartbeat
    await job(pp(8, 10))
    assert await offline_alerts() == 2 and "last seen 08:00" in (await ops_texts())[-1][1]
    await beat(client, pp(8, 12), monkeypatch)
    assert await job(pp(21, 30)) == 0  # closed again: silence is fine
    assert all(str(PP2) not in t for t, _ in await ops_texts())  # PP2 has no opening hours: never


async def test_late_opening_once_and_not_when_there_was_a_sale(client) -> None:
    await event("branch.settings_updated", {"branch_id": str(PP2), "opening_hours": HOURS})
    await event("invoice.created", {"invoice_id": str(uuid4()), "status": "completed", "number": "PP2-INV-1",
                                    "branch": {"id": str(PP2)}, "completed_at": pp(7, 10).isoformat(), "lines": []})  # fmt: skip
    await job(pp(7, 29))
    assert [t for t in await ops_texts() if "no sale yet" in t[1]] == []
    await job(pp(7, 30))
    await job(pp(7, 45))
    late = [t for t in await ops_texts() if "no sale yet" in t[1]]
    assert [t for t, _ in late] == [str(PP1), "owner"] and "30 minutes after opening (07:00)" in late[0][1]


async def test_the_summary_shows_the_first_and_last_sale() -> None:
    figures = {"today": {"date": "2026-10-27", "net_sales": "1", "net_sales_khr": 4100, "invoices": 1,
                         "average_basket": "1", "returns": "0"},
               "same_day_last_week": {"net_sales": "0"}, "near_expiry": {"count": 0}, "first_sale": "07:12",
               "last_sale": "19:40"}  # fmt: skip
    assert "First sale 07:12 · last sale 19:40" in texts.daily_summary("PP1", figures, profit=False)


async def sensors_on() -> None:
    await event("feature.changed", {"key": "fridge_sensors", "enabled": True})


async def reading(client, token: str, temp: str, at: datetime, monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(clock, "now", lambda: at)
    return await client.post(f"{PREFIX}/sensors/readings", json={"temperature_c": temp, "battery": 90},
                             headers={"Authorization": f"Bearer {token}"})  # fmt: skip


async def test_sensor_device_list_and_tokens(client) -> None:
    r = await client.post(f"{PREFIX}/sensors", json={"branch_id": str(PP2), "name": "Fridge A"}, headers=MANAGER)
    assert r.status_code == 403  # not their branch
    r = await client.post(f"{PREFIX}/sensors", json={"branch_id": str(PP1), "name": "Fridge A", "min_c": "8",
                                                     "max_c": "2"}, headers=MANAGER)  # fmt: skip
    assert r.status_code == 422 and r.json()["details"]["reason"] == "min_above_max"
    r = await client.post(f"{PREFIX}/sensors", json={"branch_id": str(PP1), "name": "Fridge A"}, headers=MANAGER)
    d = r.json()
    assert (d["min_c"], d["max_c"], d["state"]) == ("2.00", "8.00", "ok") and d["token"].startswith("fs_")
    listed = (await client.get(f"{PREFIX}/sensors", headers=MANAGER)).json()
    assert [x["name"] for x in listed] == ["Fridge A"] and listed[0]["token"] is None  # shown once only
    assert (await client.get(f"{PREFIX}/sensors", headers=user("cashier", "pos.sell"))).status_code == 403
    renewed = (await client.post(f"{PREFIX}/sensors/{d['id']}/token", headers=MANAGER)).json()["token"]
    assert renewed != d["token"]


async def test_sensor_alerts_after_10_minutes_back_in_range_and_silent(client, monkeypatch) -> None:
    d = (await client.post(f"{PREFIX}/sensors", json={"branch_id": str(PP1), "name": "Fridge A"}, headers=MANAGER)).json()
    token, t0 = d["token"], pp(9, 0)
    assert (await reading(client, token, "5.0", t0, monkeypatch)).status_code == 404  # feature off
    await sensors_on()
    assert (await reading(client, "fs_wrong", "5.0", t0, monkeypatch)).status_code == 401
    r = await reading(client, token, "5.0", t0, monkeypatch)
    assert r.json() == {"ok": True, "in_range": True, "state": "ok"}
    await reading(client, token, "9.4", t0 + timedelta(minutes=1), monkeypatch)
    await reading(client, token, "9.6", t0 + timedelta(minutes=10), monkeypatch)  # out for 9 minutes
    assert await ops_texts() == []
    await reading(client, token, "9.8", t0 + timedelta(minutes=12), monkeypatch)  # 11 minutes
    rows = await ops_texts()
    assert [t for t, _ in rows] == [str(PP1), "owner"]
    assert "Fridge A: 9.8 °C for 11 minutes (allowed 2–8 °C)" in rows[0][1]
    await reading(client, token, "9.9", t0 + timedelta(minutes=13), monkeypatch)
    assert len(await ops_texts()) == 2  # once
    await reading(client, token, "6.1", t0 + timedelta(minutes=20), monkeypatch)
    assert "back in range, 6.1 °C (out 09:01–09:20)" in (await ops_texts())[-1][1]
    async def silent() -> list[str]:
        return [x for t, x in await ops_texts() if t == "owner" and "no reading for 30 minutes" in x]

    await job(t0 + timedelta(minutes=49))
    assert await silent() == []
    await job(t0 + timedelta(minutes=50))  # no reading for 30 minutes
    await job(t0 + timedelta(minutes=55))
    assert len(await silent()) == 1 and "(last 09:20)" in (await silent())[0]


async def test_sparse_readings_are_caught_by_the_minute_job(client, monkeypatch) -> None:
    await sensors_on()
    d = (await client.post(f"{PREFIX}/sensors", json={"branch_id": str(PP1), "name": "Fridge B", "min_c": "2",
                                                      "max_c": "8"}, headers=MANAGER)).json()  # fmt: skip
    t0 = pp(9, 0)
    await reading(client, d["token"], "1.0", t0, monkeypatch)  # too cold, then the device reports every 15 min

    async def fridge() -> list[str]:
        return [x for t, x in await ops_texts() if t == "owner" and "Fridge B" in x]

    await job(t0 + timedelta(minutes=10))
    assert await fridge() == []
    await job(t0 + timedelta(minutes=11))
    assert len(await fridge()) == 1 and "1.0 °C for 11 minutes" in (await fridge())[0]


async def test_fridge_min_max_in_the_morning_digest(client, monkeypatch) -> None:
    await sensors_on()
    d = (await client.post(f"{PREFIX}/sensors", json={"branch_id": str(PP1), "name": "Fridge A"}, headers=MANAGER)).json()
    for minute, temp in ((0, "4.0"), (5, "8.6"), (10, "2.4")):
        await reading(client, d["token"], temp, pp(10, minute, 26), monkeypatch)
    async with db.sessionmaker() as s:
        assert await stock_digest(s, app.state.settings, date(2026, 10, 27)) == 1
    digest = next(m for m in await messages() if m.kind == "stock_digest")
    assert "Fridges yesterday:" in digest.text and "• Fridge A: 2.4–8.6 °C (3) · 1 ក្រៅកម្រិត / out of range" in digest.text
