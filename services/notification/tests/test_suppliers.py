"""T2 phase 5: supplier chats – linked by staff, a sent PO goes as a PDF with a confirm button, the tap is recorded
once (purchasing) and only from a chat linked to that supplier; clinics are covered in test_customer_telegram."""

from uuid import UUID, uuid4

import pytest

from notification_service.db import db
from notification_service.main import app
from notification_service.services import bot
from notification_service.services.staff_bot import Hooks

from .conftest import PP1, PREFIX, event, messages, sender, user

SECRET = "w" * 40
SUPPLIER, OTHER = uuid4(), uuid4()
BUYER = user("branch_manager", "purchasing.order")


class Purchasing:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    def __call__(self, name: str):  # noqa: ANN204
        assert name == "purchasing"
        return self

    async def post(self, path: str, body: dict, **_: object) -> dict:
        self.posts.append((path, body))
        return {"number": "PP1-PO-2026-000007", "supplier_confirmed_at": "2026-10-27T03:00:00+00:00",
                "supplier_confirmed_by": self.posts[0][1]["by"]}  # the first confirmation stays  # fmt: skip


@pytest.fixture
def fakes(telegram, documents):  # noqa: ANN001, ANN201
    s = app.state.settings
    s.telegram_bot_username, s.telegram_webhook_secret = "pharma_test_bot", SECRET
    f = Purchasing()
    old, bot.HOOKS = bot.HOOKS, Hooks(f)
    yield f
    bot.HOOKS = old
    s.telegram_bot_username, s.telegram_webhook_secret = "", ""


_n = iter(range(1, 10_000_000))


async def hook(client, update: dict) -> None:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/telegram/webhook", json={"update_id": next(_n), **update},
                          headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})  # fmt: skip
    assert r.status_code == 200


async def link(client, supplier: UUID, label: str, chat: str, kind: str = "group") -> None:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/suppliers/{supplier}/telegram/link-token", json={"label": label}, headers=BUYER)
    assert r.status_code == 200, r.text
    token = r.json()["url"].split("start=")[1]
    assert token.startswith("p")
    await hook(client, {"message": {"message_id": 1, "chat": {"id": int(chat), "type": kind}, "from": {"id": 55},
                                    "text": f"/start {token}"}})  # fmt: skip


def po(status: str = "sent") -> dict:
    return {"purchase_order_id": "00000000-0000-0000-0000-0000000000b7", "number": "PP1-PO-2026-000007", "status": status,
            "branch": {"id": str(PP1), "code": "PP1", "name_en": "Toul Kork", "name_km": "ទួលគោក"},
            "supplier": {"id": str(SUPPLIER), "code": "DKSH"}, "expected_on": "2026-11-02", "total": "120.00", "lines": []}  # fmt: skip


async def test_sent_po_goes_to_every_linked_chat_and_the_confirmation_is_recorded(client, fakes, telegram) -> None:
    assert (await client.post(f"{PREFIX}/suppliers/{SUPPLIER}/telegram/link-token", json={"label": "x"},
                              headers=user("cashier", "pos.sell"))).status_code == 403  # fmt: skip
    await link(client, SUPPLIER, "Sales – Vuthy", "-200100")
    await link(client, SUPPLIER, "Accounts", "7700", "private")
    await link(client, OTHER, "Another supplier", "-200300")
    status = (await client.get(f"{PREFIX}/suppliers/{SUPPLIER}/telegram", headers=BUYER)).json()
    assert sorted(x["label"] for x in status["links"]) == ["Accounts", "Sales – Vuthy"]
    await event("purchase_order.sent", po())
    await event("purchase_order.sent", po())  # a replayed event: nothing new
    rows = [m for m in await messages() if m.kind == "purchase_order"]
    assert sorted(m.chat_id for m in rows) == ["-200100", "7700"]
    assert rows[0].document == {"type": "purchase_order", "id": po()["purchase_order_id"], "lang": "en"}
    assert "ការបញ្ជាទិញ PP1-PO-2026-000007 ពី ទួលគោក · 02/11/2026" in rows[0].text and "from Toul Kork" in rows[0].text
    log = (await client.get(f"{PREFIX}/messages", headers=user("owner", "*", ()))).json()
    assert all(x["text"] == "" for x in log if x["kind"] == "purchase_order")  # the log: summary only
    async with db.sessionmaker() as s:
        await sender().send_due(s)
    data = f"po:{UUID(po()['purchase_order_id']).hex}"
    tap = {"callback_query": {"id": "cb1", "data": data, "from": {"id": 55},
                              "message": {"message_id": 9, "chat": {"id": -200300, "type": "group"}}}}  # fmt: skip
    await hook(client, tap)  # another supplier's chat: refused
    assert fakes.posts == []
    await hook(client, {"callback_query": {**tap["callback_query"], "id": "cb2",
                                           "message": {"message_id": 9, "chat": {"id": -200100, "type": "group"}}}})  # fmt: skip
    assert fakes.posts == [(f"/purchase-orders/{po()['purchase_order_id']}/supplier-confirm",
                            {"supplier_id": str(SUPPLIER), "by": "Sales – Vuthy"})]  # fmt: skip
    async with db.sessionmaker() as s:
        await sender().send_due(s)
    edit = next(x for x in telegram.sent if x["_method"] == "editMessageCaption")
    assert "Confirmed by Sales – Vuthy · 27/10 10:00" in edit["caption"] and edit["reply_markup"] == {"inline_keyboard": []}
    told = [m for m in await messages() if m.kind == "ops" and m.target == str(PP1)]
    assert len(told) == 1 and "PP1-PO-2026-000007" in told[0].text
    r = await client.post(f"{PREFIX}/suppliers/{SUPPLIER}/telegram/unlink", headers=BUYER,
                          json={"link_id": status["links"][0]["id"]})  # fmt: skip
    assert len(r.json()["links"]) == 1
