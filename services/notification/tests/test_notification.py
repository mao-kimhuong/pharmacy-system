"""Telegram: chats and permissions, the test message, the 20:00 summary (once per
chat, never changed), retries with backoff and Telegram's retry_after, the alerts,
the 07:30 stock digest, and no patient data in any message."""

from datetime import timedelta
from uuid import uuid4

import httpx

from notification_service.config import get_settings
from notification_service.db import db
from notification_service.main import app
from notification_service.models import Message
from notification_service.services.jobs import daily_summary, stock_digest
from notification_service.services.telegram import Sender

from .conftest import MANAGER, NOW, OWNER, PP1, PP2, PREFIX, TODAY, TOKEN, FakeTelegram, event, messages, user


def figures(net: str = "120.50") -> dict:
    day = {"date": TODAY.isoformat(), "net_sales": net, "net_sales_khr": 494000, "invoices": 30,
           "average_basket": "4.02", "returns": "1.00", "gross_profit": "40.10", "margin_pct": "33.28"}  # fmt: skip
    return {"today": day, "same_day_last_week": {**day, "net_sales": "100.00"}, "top_medicines": [
        {"sku": "PARA500", "net": "20.00"}], "low_stock": [{"sku": "ORS"}], "near_expiry": {"count": 2},
        "open_controlled_discrepancies": 1, "pending_approvals": {"shrinkages": 1, "stock_takes": 0}}  # fmt: skip


class Reports:
    def __init__(self) -> None:
        self.net = "120.50"
        self.calls: list[dict] = []

    async def get(self, path: str, params: dict) -> dict:
        assert path == "/daily-summary"
        self.calls.append(params)
        return figures(self.net)


async def set_chats(client) -> None:  # noqa: ANN001
    assert (await client.put(f"{PREFIX}/chats/owner", json={"chat_id": "-1001"}, headers=OWNER)).status_code == 200
    assert (await client.put(f"{PREFIX}/chats/{PP1}", json={"chat_id": "-1002"}, headers=MANAGER)).status_code == 200


async def test_changing_a_saved_chat_answers_with_the_new_one(client) -> None:
    # regression: updated_at expired at commit was loaded lazily in the response → 500 (MissingGreenlet)
    await set_chats(client)
    r = await client.put(f"{PREFIX}/chats/{PP1}", json={"chat_id": "-1003", "is_active": False}, headers=MANAGER)
    assert r.status_code == 200 and r.json()["chat_id"] == "-1003" and r.json()["is_active"] is False


async def test_chats_and_who_may_set_them(client) -> None:
    await set_chats(client)
    assert (await client.put(f"{PREFIX}/chats/owner", json={"chat_id": "-5555"}, headers=MANAGER)).status_code == 403
    assert (await client.put(f"{PREFIX}/chats/{PP2}", json={"chat_id": "-5555"}, headers=MANAGER)).status_code == 403
    assert (await client.put(f"{PREFIX}/chats/{PP1}", json={"chat_id": "not a chat"}, headers=MANAGER)).status_code == 422
    assert (await client.get(f"{PREFIX}/chats", headers=user("cashier", "pos.sell"))).status_code == 403
    seen = (await client.get(f"{PREFIX}/chats", headers=MANAGER)).json()
    assert [c["target"] for c in seen] == [str(PP1)]  # not the owner's


async def test_test_message_with_and_without_a_token(client, monkeypatch) -> None:
    await set_chats(client)
    r = await client.post(f"{PREFIX}/test", json={"target": "owner"}, headers=OWNER)
    assert r.status_code == 503 and r.json()["code"] == "TELEGRAM_NOT_CONFIGURED"
    assert [(m.kind, m.status, m.last_error) for m in await messages()] == [("test", "skipped", "no bot token")]
    fake = FakeTelegram()
    app.state.settings.telegram_bot_token = TOKEN
    app.state.telegram_transport = httpx.MockTransport(fake)
    try:
        monkeypatch.setattr("pharmacy_shared.clock.now", lambda: NOW + timedelta(seconds=1))
        r = await client.post(f"{PREFIX}/test", json={"target": str(PP1)}, headers=MANAGER)
    finally:
        app.state.telegram_transport = None
    assert r.status_code == 200 and r.json()["status"] == "sent", r.text
    assert fake.sent[0]["chat_id"] == "-1002" and "Test message" in fake.sent[0]["text"]
    listed = (await client.get(f"{PREFIX}/messages", headers=MANAGER)).json()
    assert [m["status"] for m in listed] == ["sent"]  # the owner's test message is not the manager's to see


async def test_daily_summary_once_per_chat_and_never_changed(client) -> None:
    await set_chats(client)
    settings = get_settings().model_copy(update={"telegram_bot_token": TOKEN})
    reports = Reports()
    async with db.sessionmaker() as s:
        assert await daily_summary(s, settings, reports, TODAY) == 2  # PP1 (has a chat) + the owner
    reports.net = "999.99"  # a late return changes the figures…
    async with db.sessionmaker() as s:
        assert await daily_summary(s, settings, reports, TODAY) == 0  # …the job runs again: nothing new
    sent = {m.target: m for m in await messages()}
    assert set(sent) == {"owner", str(PP1)} and all(m.status == "queued" for m in sent.values())
    assert "120.50" in sent[str(PP1)].text and "999.99" not in sent[str(PP1)].text
    assert "Gross profit" in sent["owner"].text and "Gross profit" not in sent[str(PP1)].text  # choice H
    assert "+20% vs last week" in sent["owner"].text
    r = await client.post(f"{PREFIX}/daily-summary/run", headers=MANAGER)
    assert r.status_code == 403


async def test_retry_backoff_retry_after_and_give_up(monkeypatch) -> None:
    fake = FakeTelegram()
    settings = get_settings().model_copy(update={"telegram_bot_token": TOKEN, "max_attempts": 3})
    sender = Sender(settings, httpx.MockTransport(fake))
    async with db.sessionmaker() as s:
        s.add(Message(dedupe_key="k1", target="owner", chat_id="-1", kind="test", text="hi", status="queued",
                      attempts=0, next_attempt_at=NOW))  # fmt: skip
        await s.commit()
    fake.replies = [(500, {"ok": False, "description": "Bad Gateway"}),
                    (429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 7}}),
                    (502, {})]  # fmt: skip
    async with db.sessionmaker() as s:
        assert await sender.send_due(s) == 1
    (m,) = await messages()
    assert (m.status, m.attempts, m.next_attempt_at - NOW) == ("queued", 1, timedelta(seconds=30))
    async with db.sessionmaker() as s:
        assert await sender.send_due(s) == 0  # not due yet
    monkeypatch.setattr("pharmacy_shared.clock.now", lambda: NOW + timedelta(seconds=31))
    async with db.sessionmaker() as s:
        await sender.send_due(s)
    (m,) = await messages()
    assert m.attempts == 2 and m.next_attempt_at == NOW + timedelta(seconds=31 + 7)  # Telegram's retry_after
    monkeypatch.setattr("pharmacy_shared.clock.now", lambda: NOW + timedelta(seconds=60))
    async with db.sessionmaker() as s:
        await sender.send_due(s)
    (m,) = await messages()
    assert (m.status, m.attempts, m.last_error) == ("failed", 3, "502")
    async with db.sessionmaker() as s:
        s.add(Message(dedupe_key="k2", target="owner", chat_id="-1", kind="test", text="hi", status="queued",
                      attempts=0, next_attempt_at=NOW))  # fmt: skip
        await s.commit()
        assert await sender.send_due(s) == 1
    assert {m.dedupe_key: m.status for m in await messages()}["k2"] == "sent"


PATIENT = {"patient_name_en": "Chan Dara Secret", "patient_name_km": "ចាន់ ដារា", "prescription_number": "PP1-RX-2026-000042",
           "doctor_name": "Dr Hidden Doctor", "patient_id_document": "ID-998877", "is_controlled": False}  # fmt: skip


def sale(net: str, cost: str, manual: str = "0.00", line_total: str = "10.00") -> dict:
    return {"invoice_id": str(uuid4()), "number": "PP1-INV-2026-000007", "status": "completed",
            "branch": {"id": str(PP1)}, "cashier_id": str(CASHIER_ID), "patient_id": str(uuid4()),
            "customer": {"id": str(uuid4()), "name": "Customer Secret Name", "phone": "012999888"},
            "lines": [{"sku": "AMOX500", "name": "Amoxil", "qty": 1, "pack_unit": "box", "line_total": line_total,
                       "net": net, "cost": cost, "manual_discount": manual, "promo_discount": "0.00", "rx": PATIENT,
                       "rx_item_id": str(uuid4())}]}  # fmt: skip


CASHIER_ID = uuid4()


async def test_alerts_go_out_once_with_no_patient_data(client) -> None:
    await set_chats(client)
    await event("user.created", {"user_id": str(CASHIER_ID), "name": "Sokha", "role": "cashier",
                                 "branch_ids": [str(PP1)]})  # fmt: skip
    below = sale("4.00", "6.00")
    await event("invoice.created", below)
    await event("invoice.created", below)  # delivered twice (another message id): still once per chat
    await event("invoice.created", sale("7.50", "2.00", manual="2.50"))  # 25 % ≥ 20 %
    await event("invoice.created", sale("9.50", "2.00", manual="0.50"))  # 5 %: no alert
    await event("register.discrepancy", {"discrepancy_id": str(uuid4()), "branch_id": str(PP1), "lot_no": "D1",
                                         "register_qty": 10, "stock_qty": 9})  # fmt: skip
    await event("register.chain_broken", {"branch_id": str(PP1), "medicine_id": str(uuid4())})
    await event("user.pin_locked", {"user_id": str(CASHIER_ID), "branch_id": str(PP1)})
    await event("user.locked", {"user_id": str(CASHIER_ID), "ip": "1.2.3.4"})
    got = await messages()
    kinds = sorted((m.kind, m.target == "owner") for m in got)
    assert kinds == sorted([(k, o) for k in ("below_cost", "large_discount", "controlled", "controlled", "lockout",
                                             "lockout") for o in (True, False)])  # fmt: skip
    owner_below = next(m for m in got if m.kind == "below_cost" and m.target == "owner")
    branch_below = next(m for m in got if m.kind == "below_cost" and m.target != "owner")
    assert "cost 6.00" in owner_below.text and "cost" not in branch_below.text.split("sold below cost")[1]
    assert "Sokha" in owner_below.text and "PIN" in next(m.text for m in got if "PIN" in m.text)
    for m in got:
        for secret in ("Chan Dara", "ចាន់", "RX-2026", "Hidden Doctor", "ID-998877", "Customer Secret", "012999888"):
            assert secret not in m.text, (m.kind, secret)
    assert all(m.status == "skipped" for m in got)  # no bot token in this test: kept, never sent by surprise


async def test_stock_digest_once_per_branch_and_day(client) -> None:
    await set_chats(client)
    for sku in ("ORS", "PARA500"):
        await event("stock.low", {"branch_id": str(PP1), "medicine_id": str(uuid4()), "sku": sku, "name": sku,
                                  "available": 3, "reorder_point": 20, "day": TODAY.isoformat()})  # fmt: skip
    await event("batch.expiring", {"branch_id": str(PP2), "batch_id": str(uuid4()), "medicine_id": str(uuid4()),
                                   "sku": "AMOX500", "lot_no": "L1", "expiry_date": "2026-11-20", "days_left": 24,
                                   "qty_base": 40, "day": TODAY.isoformat()})  # fmt: skip
    settings = get_settings().model_copy(update={"telegram_bot_token": TOKEN})
    async with db.sessionmaker() as s:
        assert await stock_digest(s, settings, TODAY) == 2
    async with db.sessionmaker() as s:
        assert await stock_digest(s, settings, TODAY) == 0
    got = {m.target: m for m in await messages() if m.kind == "stock_digest"}
    assert "Low stock (2)" in got[str(PP1)].text and got[str(PP1)].status == "queued"
    assert "AMOX500 lot L1" in got["owner"].text  # PP2 has no chat: the owner gets its digest


async def test_khqr_refund_and_recall_alerts(client) -> None:
    await set_chats(client)
    await event("khqr.needs_refund", {"khqr_id": str(uuid4()), "branch_id": str(PP1), "amount": "48.00",
                                      "currency": "USD", "bank_ref": "B-77", "reason": "OUT_OF_STOCK"})  # fmt: skip
    await event("batch.recalled", {"recall_id": str(uuid4()), "number": "RC-2026-000001", "branch_id": str(PP1),
                                   "sku": "AMOX500", "lots": ["L1"], "qty_base": 40})  # fmt: skip
    got = {(m.kind, m.target) for m in await messages()}
    assert got == {("khqr_refund", "owner"), ("khqr_refund", str(PP1)), ("recall", "owner"), ("recall", str(PP1))}


async def test_two_factor_off_or_reset_alerts_only_the_owner_with_no_secrets() -> None:
    await event("user.2fa_disabled", {"user_id": str(CASHIER_ID), "by": "self", "occurred_at": "2026-11-06T01:00:00+00:00"})
    await event("user.2fa_reset", {"user_id": str(CASHIER_ID), "by": "owner", "occurred_at": "2026-11-06T01:00:00+00:00"})
    await event("user.2fa_reset", {"user_id": str(uuid4()), "by": "server", "occurred_at": "2026-11-06T01:00:00+00:00"})
    got = [m for m in await messages() if m.kind == "security"]
    assert len(got) == 3 and all(m.target == "owner" for m in got)
    assert any("turned off" in m.text for m in got) and any("reset by the owner" in m.text for m in got)
    assert any("A user had two-factor login reset on the server" in m.text for m in got)
    for m in got:
        assert str(CASHIER_ID) not in m.text and "2026" not in m.text
