"""T2 phase 1: customer Telegram – linking (phone check), consent, /stop, /settings,
quiet hours, the privacy scan of every template, refill reminders, the promotion cap,
chat roles, the webhook secret, no duplicates."""

import inspect
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from notification_service.db import db
from notification_service.main import app
from notification_service.models import (
    CustomerConsent,
    LinkToken,
    Message,
    OutboxEvent,
    RefillReminder,
    TelegramLink,
)
from notification_service.services import customer_admin, customers, links
from notification_service.services import customer_texts as ct
from notification_service.services.telegram import NotAllowed, queue, quiet_until
from pharmacy_shared import clock

from .conftest import NOW, PP1, PREFIX, event, messages, sender, user

SECRET = "w" * 40
SERVICE = "s" * 40
CUSTOMER = UUID("00000000-0000-0000-0000-00000000c001")
PHONE = "012345678"
CHAT = "5550001"
STAFF = user("branch_manager", "notifications.customers,contacts.customers")
CASHIER = user("cashier", "contacts.customers")
# Planted everywhere: none of these may ever reach a chat (privacy scan)
SECRETS = ("Penicillin allergy", "Diabetes type 2", "Dr. Sok Secret", "LIC-99881", "Patient Secret Name",
           "ID-PASSPORT-777", "suspected pneumonia", "take with care: kidney failure", "Customer Real Name")  # fmt: skip


@pytest.fixture
def bot(telegram, documents):  # noqa: ANN001, ANN201
    s = app.state.settings
    s.telegram_bot_username, s.telegram_webhook_secret, s.service_token = "pharma_test_bot", SECRET, SERVICE
    yield telegram
    s.telegram_bot_username, s.telegram_webhook_secret, s.service_token = "", "", ""


async def customer(cid: UUID = CUSTOMER, phone: str = PHONE, lang: str = "km", group: UUID | None = None) -> None:
    await event("customer.created", {"customer_id": str(cid), "phone": phone, "name": "Customer Real Name",
                                     "name_km": "", "preferred_lang": lang, "is_active": True,
                                     "group_id": str(group) if group else None})  # fmt: skip


_n = iter(range(1, 10_000_000))


def msg(text: str, chat: str = CHAT, user_id: str | None = None, kind: str = "private") -> dict:
    return {"update_id": next(_n), "message": {"message_id": next(_n), "chat": {"id": int(chat), "type": kind},
                                               "from": {"id": int(user_id or chat)}, "text": text}}  # fmt: skip


def contact(phone: str, chat: str = CHAT, owner: str | None = None) -> dict:
    return {"update_id": next(_n), "message": {"message_id": next(_n), "chat": {"id": int(chat), "type": "private"},
                                               "from": {"id": int(chat)},
                                               "contact": {"phone_number": phone, "user_id": int(owner or chat)}}}  # fmt: skip


def tap(data: str, message_id: int = 77, chat: str = CHAT) -> dict:
    return {"update_id": next(_n), "callback_query": {"id": f"cb{next(_n)}", "data": data, "from": {"id": int(chat)},
                                                      "message": {"message_id": message_id,
                                                                  "chat": {"id": int(chat), "type": "private"}}}}  # fmt: skip


async def hook(client, update: dict, secret: str = SECRET):  # noqa: ANN001, ANN201
    return await client.post(f"{PREFIX}/telegram/webhook", json=update,
                             headers={"X-Telegram-Bot-Api-Secret-Token": secret})  # fmt: skip


async def printed_link(client, ref: str = "invoice:1") -> str:  # noqa: ANN001
    r = await client.post("/internal/v1/link-tokens", json={"customer_id": str(CUSTOMER), "ref": ref, "via": "receipt"},
                          headers={"X-Service-Token": SERVICE})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()["url"]


async def link_customer(client, bot) -> None:  # noqa: ANN001
    url = await printed_link(client)
    assert (await hook(client, msg(f"/start {url.split('start=')[1]}"))).status_code == 200
    assert (await hook(client, contact("+855 12 345 678"))).status_code == 200
    assert "បានភ្ជាប់" in bot.sent[-1]["text"] or "Linked!" in bot.sent[-1]["text"]


async def active() -> list[TelegramLink]:
    async with db.sessionmaker() as s:
        return list((await s.execute(select(TelegramLink).where(TelegramLink.unlinked_at.is_(None)))).scalars())


async def consents() -> dict[str, bool]:
    async with db.sessionmaker() as s:
        return {c.topic: c.granted for c in (await s.execute(select(CustomerConsent))).scalars()}


def invoice(number: str = "PP1-INV-2026-000123", cid: UUID = CUSTOMER, **extra) -> dict:  # noqa: ANN003
    return {"invoice_id": str(extra.pop("invoice_id", uuid4())), "version": 1, "number": number,
            "status": "completed", "branch": {"id": str(PP1), "code": "PP1", "name_en": "Toul Kork", "name_km": "ទួលគោក"},
            "customer": {"id": str(cid), "name": "Customer Real Name", "phone": PHONE}, "cashier_id": str(uuid4()),
            "patient_id": str(uuid4()), "completed_at": NOW.isoformat(), "total": "12.50", "total_khr": 51300,
            "lines": [{"line_no": 1, "sku": "AMX500", "name": "Amoxicillin 500", "qty": 1, "pack_unit": "box",
                       "line_total": "12.50", "net": "12.50", "cost": "8.00", "manual_discount": "0", "promo_discount": "0",
                       "rx": {"prescription_number": "PP1-RX-2026-000009", "patient_name_en": "Patient Secret Name",
                              "patient_name_km": "Patient Secret Name", "doctor_name": "Dr. Sok Secret",
                              "patient_id_document": "ID-PASSPORT-777", "allergy_override_reason": "Penicillin allergy",
                              "warnings": [{"kind": "allergy", "message": "Penicillin allergy"}],
                              "dosage": "take with care: kidney failure", "frequency": "suspected pneumonia"}}],
            "returns": [], "payments": [], **extra}  # fmt: skip


# ------------------------------------------------------------------ linking


async def test_printed_link_needs_the_customers_own_phone(client, bot) -> None:
    await customer()
    url = await printed_link(client)
    assert url.startswith("https://t.me/pharma_test_bot?start=c") and len(url.split("start=")[1]) <= 64
    assert await printed_link(client) == url  # a reprint shows the same QR
    token = url.split("start=")[1]
    await hook(client, msg(f"/start {token}"))
    assert bot.sent[-1]["reply_markup"]["keyboard"][0][0]["request_contact"] is True
    assert not await active()
    await hook(client, contact("012345678", owner="999"))  # someone else's contact card
    assert not await active() and "own phone" in bot.sent[-1]["text"]
    await hook(client, contact("+855 12 345 678"))
    links_now = await active()
    assert [(x.role, x.subject_id, x.chat_id, x.via) for x in links_now] == [("customer", CUSTOMER, CHAT, "receipt")]
    assert await consents() == {"receipts": True, "reminders": True, "balance": True, "orders": True}  # not marketing
    async with db.sessionmaker() as s:
        logged = [e.payload["action"] for e in (await s.execute(select(OutboxEvent))).scalars()
                  if e.event_type == "audit.recorded"]  # fmt: skip
    assert "telegram.customer_linked" in logged and "telegram.consent_changed" in logged
    # used: the same token links nothing again, and a new print gets no QR (already linked)
    await hook(client, msg(f"/start {token}", chat="5550002"))
    assert "can no longer be used" in bot.sent[-1]["text"]
    assert await printed_link(client, "invoice:2") is None


async def test_phone_mismatch_links_nothing_and_cannot_retry(client, bot) -> None:
    await customer()
    token = (await printed_link(client)).split("start=")[1]
    await hook(client, msg(f"/start {token}"))
    await hook(client, contact("+855 99 999 999"))
    assert not await active() and "does not match" in bot.sent[-1]["text"]
    await hook(client, contact("+855 12 345 678"))  # the right number now: this chat had its try
    assert not await active()


async def test_counter_link_has_no_phone_check_and_groups_cannot_link(client, bot) -> None:
    await customer()
    assert (await client.post(f"{PREFIX}/customers/{CUSTOMER}/telegram/link-token", headers=CASHIER)).status_code == 403
    r = await client.post(f"{PREFIX}/customers/{CUSTOMER}/telegram/link-token", headers=STAFF)
    token = r.json()["url"].split("start=")[1]
    await hook(client, msg(f"/start {token}", chat="-100777", kind="group"))
    assert not await active() and "private chat" in bot.sent[-1]["text"]
    await hook(client, msg(f"/start {token}"))
    assert [x.via for x in await active()] == ["counter"]
    status = (await client.get(f"{PREFIX}/customers/{CUSTOMER}/telegram", headers=CASHIER)).json()
    assert status["linked"] and {c["topic"]: c["source"] for c in status["consents"]}["receipts"] == "bot_start"


async def test_tokens_expire_after_7_days(client, bot, monkeypatch) -> None:
    await customer()
    token = (await printed_link(client)).split("start=")[1]
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(days=7, seconds=1))
    await hook(client, msg(f"/start {token}"))
    assert "can no longer be used" in bot.sent[-1]["text"]


async def test_staff_tokens_last_15_minutes(bot) -> None:
    async with db.sessionmaker() as s:
        token = await links.issue(s, app.state.settings, role="staff", subject_id=uuid4(), ref="profile:x",
                                  via="profile", phone_check=False)  # fmt: skip
        row = await s.get(LinkToken, links.token_hash(token))
        assert row.expires_at - NOW == timedelta(minutes=15)


# ------------------------------------------------------------------ consent, /stop, /settings


async def test_receipt_only_with_consent_in_the_customers_language(client, bot) -> None:
    await customer(lang="en")
    await event("invoice.created", invoice("PP1-INV-2026-000001"))
    assert not await messages()  # not linked: nothing at all
    await link_customer(client, bot)
    inv = invoice()
    assert await event("invoice.created", inv)
    await event("invoice.created", {**inv})  # the same invoice again (another message id): still one receipt
    rows = [m for m in await messages() if m.kind == "receipt"]
    assert len(rows) == 1
    m = rows[0]
    assert m.document == {"type": "invoice_a4", "id": inv["invoice_id"], "lang": "en"}
    assert m.summary == "Receipt PP1-INV-2026-000123 → customer …5678"
    assert "Receipt PP1-INV-2026-000123: 12.50 USD (51,300 KHR)" in m.text
    log = (await client.get(f"{PREFIX}/messages", headers=user("owner", "*", ()))).json()
    shown = next(x for x in log if x["kind"] == "receipt")
    assert shown["text"] == "" and shown["target"] == "customer" and shown["summary"].startswith("Receipt")
    async with db.sessionmaker() as s:
        await sender().send_due(s)
    doc = next(x for x in bot.sent if x["_method"] == "sendDocument")
    assert 'name="chat_id"' in doc["_raw"] and CHAT in doc["_raw"] and "invoice_a4.pdf" in doc["_raw"]
    async with db.sessionmaker() as s:
        sent = await s.get(Message, m.id)
        assert sent.status == "sent" and sent.text == "" and sent.summary  # the text is gone, the summary stays


async def test_stop_unlinks_and_turns_everything_off(client, bot) -> None:
    await customer()
    await link_customer(client, bot)
    await hook(client, msg("/stop"))
    assert not await active() and set((await consents()).values()) == {False}
    await event("invoice.created", invoice())
    assert not [m for m in await messages() if m.kind == "receipt"]


async def test_settings_buttons_toggle_one_topic(client, bot) -> None:
    await customer(lang="en")
    await link_customer(client, bot)
    await hook(client, msg("/settings"))
    keyboard = bot.sent[-1]["reply_markup"]["inline_keyboard"]
    assert [row[0]["callback_data"] for row in keyboard][:6] == [f"cs:{t}" for t in ct.TOPIC_LABELS]
    await hook(client, tap("cs:receipts", message_id=88))
    assert (await consents())["receipts"] is False
    edit = bot.sent[-1]
    assert edit["_method"] == "editMessageText" and edit["message_id"] == "88"
    assert edit["reply_markup"]["inline_keyboard"][0][0]["text"].startswith("⬜")
    assert any(c["_method"] == "answerCallbackQuery" for c in bot.calls)
    await event("invoice.created", invoice())
    assert not [m for m in await messages() if m.kind == "receipt"]
    await hook(client, tap("cs:marketing"))
    assert (await consents())["marketing"] is True


async def test_staff_can_record_consent_but_never_turn_marketing_on(client, bot) -> None:
    await customer()
    await link_customer(client, bot)
    url = f"{PREFIX}/customers/{CUSTOMER}/telegram/consents"
    r = await client.put(url, json={"consents": {"marketing": True}}, headers=STAFF)
    assert r.status_code == 403 and r.json()["details"]["reason"] == "customer_only"
    r = await client.put(url, json={"consents": {"balance": False}}, headers=STAFF)
    assert {c["topic"]: (c["granted"], c["source"]) for c in r.json()["consents"]}["balance"] == (False, "staff")
    assert (await client.put(url, json={"consents": {"balance": True}}, headers=CASHIER)).status_code == 403
    r = await client.post(f"{PREFIX}/customers/{CUSTOMER}/telegram/unlink", headers=STAFF)
    assert r.json()["linked"] is False


# ------------------------------------------------------------------ quiet hours


@pytest.mark.parametrize(("utc", "due"), [
    (datetime(2026, 10, 27, 13, 59, tzinfo=UTC), None),                                   # 20:59 Phnom Penh
    (datetime(2026, 10, 27, 14, 0, tzinfo=UTC), datetime(2026, 10, 28, 0, 0, tzinfo=UTC)),  # 21:00 → 07:00
    (datetime(2026, 10, 27, 23, 59, tzinfo=UTC), datetime(2026, 10, 28, 0, 0, tzinfo=UTC)),  # 06:59 → 07:00
    (datetime(2026, 10, 28, 0, 0, tzinfo=UTC), None),                                     # 07:00
])  # fmt: skip
def test_quiet_hours(utc: datetime, due: datetime | None) -> None:
    got = quiet_until(utc, app.state.settings)
    assert (got.astimezone(UTC) if got else None) == due


async def test_customer_messages_wait_for_morning_and_retries_too(client, bot, monkeypatch) -> None:
    await customer()
    await link_customer(client, bot)
    late = datetime(2026, 10, 27, 15, 30, tzinfo=UTC)  # 22:30
    monkeypatch.setattr(clock, "now", lambda: late)
    await event("invoice.created", invoice())
    m = next(x for x in await messages() if x.kind == "receipt")
    assert m.next_attempt_at == datetime(2026, 10, 28, 0, 0, tzinfo=UTC)
    async with db.sessionmaker() as s:  # the owner's alerts are not held back
        alert = await queue(s, app.state.settings, key="x", target="owner", kind="test", text="t")
        await s.commit()
    assert alert.next_attempt_at == late
    async with db.sessionmaker() as s:  # a retry that is due at night is pushed to 07:00, no attempt counted
        row = await s.get(Message, m.id)
        row.next_attempt_at = late
        await sender().send(s, row)
        assert row.attempts == 0 and row.next_attempt_at == datetime(2026, 10, 28, 0, 0, tzinfo=UTC)


# ------------------------------------------------------------------ privacy


def _samples() -> dict[str, dict]:
    """Every template with every argument it takes (values: allow-listed kinds only)."""
    return {
        "receipt": {"lang": "km", "branch": "Toul Kork", "number": "PP1-INV-1", "total_usd": "1", "total_khr": 4100},
        "refill": {"lang": "km", "branch": "Toul Kork", "rx_number": "PP1-RX-1", "runs_out_on": "2026-11-01",
                   "refills_left": True, "medicine": None},
        "order_ready": {"lang": "km", "branch": "Toul Kork", "number": "PP1-SO-1", "remaining_usd": "3"},
        "order_status": {"lang": "km", "branch": "Toul Kork", "number": "PP1-SO-1", "status": "ordered"},
        "balance": {"lang": "km", "balance_usd": "10", "overdue_usd": "5", "overdue_since": "2026-10-01", "overdue": True},
        "deposit_taken": {"lang": "km", "branch": "Toul Kork", "order_number": "PP1-SO-1", "amount_usd": "5"},
        "deposit_refunded": {"lang": "km", "branch": "Toul Kork", "order_number": "PP1-SO-1", "amount_usd": "5"},
        "deposit_credit": {"lang": "km", "branch": "Toul Kork", "order_number": "PP1-SO-1", "amount_usd": "5"},
        "return_refund": {"lang": "km", "branch": "Toul Kork", "return_number": "PP1-RT-1", "amount_usd": "2",
                          "method": "cash"},
        "marketing": {"lang": "km", "text_km": "បញ្ចុះតម្លៃ", "text_en": "10% off"},
        "supplier_po": {"lang": "km", "number": "PP1-PO-1", "branch": "Toul Kork", "expected_on": None},
    }  # fmt: skip


FORBIDDEN_PARAMS = {"patient", "doctor", "allergy", "allergies", "note", "notes", "diagnosis", "condition",
                    "conditions", "name", "customer_name", "id_document", "warnings", "dosage", "frequency"}  # fmt: skip


def test_every_template_takes_only_allow_listed_values() -> None:
    fns = {n: f for n, f in inspect.getmembers(ct, inspect.isfunction)
           if f.__module__ == ct.__name__ and inspect.signature(f).return_annotation is str
           and n not in ("both", "branch_name", "_d", "_usd", "_riel", "settings_text", "customer_help", "linked")}  # fmt: skip
    assert set(fns) == set(_samples()), "a new template needs a sample here (and a privacy review)"
    for name, fn in fns.items():
        params = set(inspect.signature(fn).parameters)
        assert not params & FORBIDDEN_PARAMS, f"{name} takes {params & FORBIDDEN_PARAMS}"
        for lang in ("km", "en"):
            out = fn(**{**_samples()[name], "lang": lang})
            assert out and not any(s.lower() in out.lower() for s in SECRETS)


async def test_privacy_scan_of_every_customer_message(client, bot) -> None:
    """Events full of patient data → every queued text, summary and bot reply is clean."""
    group = uuid4()
    await event("customer_group.created", {"group_id": str(group), "name_en": "Clinic", "is_clinic": True})
    await customer(group=group)
    await link_customer(client, bot)
    await hook(client, tap("cs:show_medicine_names"))
    inv = invoice()
    await event("invoice.created", inv)
    await event("invoice.returned", {**inv, "version": 2, "returns": [
        {"return_id": str(uuid4()), "number": "PP1-RT-2026-000001", "refund_usd": "2.00", "refund_method": "cash",
         "reason": "Penicillin allergy", "created_at": NOW.isoformat()}]})  # fmt: skip
    order = {"sale_order_id": str(uuid4()), "number": "PP1-SO-2026-000004", "status": "ordered", "version": 1,
             "branch": inv["branch"], "customer": inv["customer"], "note": "Diabetes type 2", "remaining_usd": "4.00",
             "ready_at": NOW.isoformat(), "lines": inv["lines"]}  # fmt: skip
    await event("sale_order.ordered", order)
    await event("sale_order.ready", order)
    await event("deposit.taken", {"deposit_id": str(uuid4()), "customer_id": str(CUSTOMER), "branch_id": str(PP1),
                                  "document_no": "PP1-SO-2026-000004", "amount": "5.00", "used": "0", "remaining": "5.00",
                                  "status": "held"})  # fmt: skip
    await event("rx.supply", supply_event(runs_out="2026-10-29", name="Amoxicillin 500"))
    async with db.sessionmaker() as s:
        assert await customers.refill_job(s, app.state.settings, date(2026, 10, 27))
    texts = [(m.kind, m.text, m.summary) for m in await messages()]
    kinds = {k for k, _, _ in texts}
    assert {"receipt", "refund", "order_status", "order_ready", "deposit", "refill"} <= kinds
    blob = "\n".join(f"{t}\n{s}" for _, t, s in texts) + "\n".join(x.get("text", "") for x in bot.sent)
    for secret in SECRETS:
        assert secret not in blob, secret
    assert "Amoxicillin 500" in next(t for k, t, _ in texts if k == "refill")  # the customer chose names


# ------------------------------------------------------------------ refill reminders


def supply_event(runs_out: str = "2026-10-30", name: str = "Amoxicillin 500", qty: int = 21, invoice_id: str | None = None,
                 version: int = 1, dispensed: str = "2026-10-20", item: str = "00000000-0000-0000-0000-0000000000e1") -> dict:  # fmt: skip
    return {"rx_item_id": item, "prescription_id": str(uuid4()), "prescription_number": "PP1-RX-2026-000009",
            "branch_id": str(PP1), "invoice_id": invoice_id or "00000000-0000-0000-0000-0000000000f1",
            "invoice_version": version, "customer_id": str(CUSTOMER), "medicine_name": name, "qty_base": qty,
            "dispensed_on": dispensed, "supply_days": 10 if qty else 0, "runs_out_on": runs_out if qty else None,
            "refills_left": True}  # fmt: skip


async def test_refill_reminder_n_days_before_without_the_medicine_name(client, bot) -> None:
    await event("branch.settings_updated", {"branch_id": str(PP1), "refill_reminder_days": 3})
    await customer(lang="en")
    await link_customer(client, bot)
    await event("rx.supply", supply_event(runs_out="2026-10-30"))
    async with db.sessionmaker() as s:
        row = await s.get(RefillReminder, UUID("00000000-0000-0000-0000-0000000000e1"))
        assert row.remind_on == date(2026, 10, 27)
        assert await customers.refill_job(s, app.state.settings, date(2026, 10, 26)) == 0  # not yet
    async with db.sessionmaker() as s:
        assert await customers.refill_job(s, app.state.settings, date(2026, 10, 27)) == 1
    async with db.sessionmaker() as s:
        assert await customers.refill_job(s, app.state.settings, date(2026, 10, 27)) == 0  # once
    m = next(x for x in await messages() if x.kind == "refill")
    assert "Your medicine from prescription PP1-RX-2026-000009 runs out around 30/10/2026" in m.text
    assert "Amoxicillin" not in m.text and "collect a refill at Branch PP1" in m.text


async def test_refill_follows_cancel_and_ignores_an_older_sale(bot) -> None:
    await customer()
    await event("rx.supply", supply_event(runs_out="2026-11-10", dispensed="2026-11-01", invoice_id=str(UUID(int=2))))
    await event("rx.supply", supply_event(runs_out="2026-10-30", dispensed="2026-10-20"))  # older sale: ignored
    async with db.sessionmaker() as s:
        assert (await s.get(RefillReminder, UUID("00000000-0000-0000-0000-0000000000e1"))).runs_out_on == date(2026, 11, 10)
    await event("rx.supply", supply_event(qty=0, invoice_id=str(UUID(int=2)), version=2))  # that sale cancelled
    async with db.sessionmaker() as s:
        assert await s.get(RefillReminder, UUID("00000000-0000-0000-0000-0000000000e1")) is None


# ------------------------------------------------------------------ promotions, roles, webhook


async def test_promotions_only_with_marketing_consent_and_at_most_two_a_month(client, bot) -> None:
    await customer()
    await link_customer(client, bot)
    body = {"title": "Nov", "text_km": "បញ្ចុះតម្លៃ ១០%", "text_en": "10% off"}
    r = await client.post(f"{PREFIX}/campaigns", json=body, headers=STAFF)
    assert r.status_code == 201 and r.json()["queued"] == 0  # marketing is off by default
    await hook(client, tap("cs:marketing"))
    got = [(await client.post(f"{PREFIX}/campaigns", json=body, headers=STAFF)).json() for _ in range(3)]
    assert [(g["queued"], g["over_cap"]) for g in got] == [(1, 0), (1, 0), (0, 1)]
    assert (await client.post(f"{PREFIX}/campaigns", json=body, headers=CASHIER)).status_code == 403


async def test_each_kind_only_for_its_chat_roles(bot) -> None:
    async with db.sessionmaker() as s:
        for target, kind in ((f"customer:{CUSTOMER}", "daily_summary"), (str(PP1), "receipt"), ("owner", "refill"),
                             (f"supplier:{uuid4()}", "receipt"), (f"customer:{CUSTOMER}", "approval")):  # fmt: skip
            with pytest.raises(NotAllowed):
                await queue(s, app.state.settings, key=f"k:{target}:{kind}", target=target, kind=kind, text="x")
        assert await queue(s, app.state.settings, key="ok", target=f"customer:{CUSTOMER}", kind="receipt", text="x")


async def test_webhook_needs_the_secret_and_handles_each_update_once(client, bot) -> None:
    update = msg("hello")
    assert (await hook(client, update, secret="wrong")).status_code == 401
    assert (await hook(client, update, secret="")).status_code == 401
    app.state.settings.telegram_webhook_secret = ""
    assert (await hook(client, update, secret="")).status_code == 401  # none configured: always refused
    app.state.settings.telegram_webhook_secret = SECRET
    assert (await hook(client, update)).status_code == 200
    assert (await hook(client, update)).status_code == 200  # Telegram retried
    assert len([x for x in bot.sent if x["_method"] == "sendMessage"]) == 1 and "This is the pharmacy" in bot.sent[0]["text"]
    await hook(client, msg("hi", chat="-100555", kind="group"))  # unknown group: no answer
    await hook(client, msg("/settings", chat="5559999"))  # unknown chat: the greeting, no data
    assert "This is the pharmacy" in bot.sent[-1]["text"] and len(bot.sent) == 2


async def test_clinic_customers_follow_order_status_others_only_ready(client, bot) -> None:
    clinic = uuid4()
    await event("customer_group.created", {"group_id": str(clinic), "is_clinic": True})
    await customer(lang="en")
    await link_customer(client, bot)
    order = {"sale_order_id": str(uuid4()), "number": "PP1-SO-2026-000004", "status": "ordered",
             "branch": {"id": str(PP1), "code": "PP1", "name_en": "Toul Kork"}, "customer": {"id": str(CUSTOMER)},
             "remaining_usd": "4.50", "ready_at": NOW.isoformat()}  # fmt: skip
    await event("sale_order.ordered", order)
    await event("sale_order.ready", order)
    kinds = [m.kind for m in await messages() if m.chat_role == "customer"]
    assert kinds == ["order_ready"]  # not a clinic
    assert "To pay at pickup: 4.50 USD" in (await messages())[-1].text
    await customer(lang="en", group=clinic)
    await event("sale_order.updated", {**order, "status": "partly_fulfilled"})
    assert "order PP1-SO-2026-000004 – partly delivered" in (await messages())[-1].text


async def test_balance_job_monthly_and_overdue_once(client, bot) -> None:
    await customer()
    await link_customer(client, bot)

    class Credit:
        overdue = "0.00"

        async def get(self, path: str, params: dict | None = None, **_: object) -> dict:
            return {"balance": "30.00", "overdue": self.overdue, "oldest_due_on": "2026-10-01"}

    credit = Credit()
    async with db.sessionmaker() as s:
        assert await customers.balance_job(s, app.state.settings, credit, date(2026, 10, 27)) == 0  # not the 1st
    async with db.sessionmaker() as s:
        assert await customers.balance_job(s, app.state.settings, credit, date(2026, 11, 1)) == 1
    credit.overdue = "12.00"
    for day in (2, 3):
        async with db.sessionmaker() as s:
            assert await customers.balance_job(s, app.state.settings, credit, date(2026, 11, day)) == (day == 2)
    rows = [m for m in await messages() if m.kind in ("balance", "overdue")]
    assert [m.kind for m in rows] == ["balance", "overdue"]
    assert rows[1].document == {"type": "customer_statement", "id": str(CUSTOMER), "lang": "km"}
    assert "ហួសកាលកំណត់: 12.00 USD" in rows[1].text


async def test_internal_link_needs_the_service_token_and_a_bot(client, bot) -> None:
    await customer()
    body = {"customer_id": str(CUSTOMER), "ref": "invoice:1", "via": "receipt"}
    assert (await client.post("/internal/v1/link-tokens", json=body)).status_code == 401
    app.state.settings.telegram_bot_username = ""
    r = await client.post("/internal/v1/link-tokens", json=body, headers={"X-Service-Token": SERVICE})
    assert r.json() == {"url": None}
    async with db.sessionmaker() as s:
        assert await customer_admin.internal_link(s, app.state.settings, {**body, "customer_id": uuid4()}) is None
