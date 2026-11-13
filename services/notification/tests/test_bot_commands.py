"""T2 phase 3: bot commands – only linked staff in their private chat or a registered chat, the user's branches and
permissions now, no cost / customer names where the chat may not see them, a rate limit per chat."""

from uuid import uuid4

import pytest

from notification_service.main import app
from notification_service.services import bot
from notification_service.services.staff_bot import NO_PERMISSION, NOT_YOURS, SLOW, Hooks

from .conftest import PP1, PP2, PREFIX, user

SECRET = "w" * 40
MGR_ID, OWNER_ID, CASHIER_ID = uuid4(), uuid4(), uuid4()
MGR_TG, OWNER_TG, CASHIER_TG = "8001", "8002", "8003"
DAY = {"day": "2026-10-27", "branches": [{"id": str(PP1), "code": "PP1", "name_en": "Branch PP1", "name_km": ""}],
       "figures": {"net_sales": "120.50", "net_sales_khr": 494000, "invoices": 15, "average_basket": "8.03",
                   "returns": "0.00"}, "top": [{"sku": "PARA500", "name": "Paracetamol", "qty_base": 40, "net": "30.00"}],
       "first_sale": "07:12", "last_sale": "19:40"}  # fmt: skip


class Fakes:
    def __init__(self) -> None:
        self.access = {
            str(MGR_ID): {"user_id": str(MGR_ID), "role": "branch_manager", "is_active": True, "branch_ids": [str(PP1)],
                          "permissions": ["dashboard.view", "reports.sales", "inventory.view", "contacts.customers",
                                          "finance.cost_profit"]},
            str(OWNER_ID): {"user_id": str(OWNER_ID), "role": "owner", "is_active": True, "branch_ids": [], "permissions": ["*"]},
            str(CASHIER_ID): {"user_id": str(CASHIER_ID), "role": "cashier", "is_active": True, "branch_ids": [str(PP1)],
                              "permissions": ["pos.sell", "inventory.view"]},
        }  # fmt: skip
        self.asked: list[tuple[str, dict]] = []
        outer = self

        class Client:
            def __init__(self, name: str) -> None:
                self.name = name

            async def get(self, path: str, params: dict | None = None, **_: object) -> dict:
                if self.name == "auth":
                    return outer.access[path.split("/")[2]]
                outer.asked.append((path, dict(params or {})))
                profit = (params or {}).get("profit") == "true"
                if path == "/bot/day":
                    figures = {**DAY["figures"], **({"gross_profit": "40.10", "margin_pct": "33.3"} if profit else {})}
                    return {**DAY, "figures": figures}
                if path == "/bot/debtors":
                    names = (params or {}).get("names") == "true"
                    return {"items": [{"customer": "Sok Dara" if names else None, "owes": "30.00"}]}
                if path == "/bot/stock":
                    return {"items": [{"sku": "PARA500", "name": "Paracetamol", "base_unit": "tablet",
                                       "on_hand": {"PP1": 120}, "total": 120}]}  # fmt: skip
                if path == "/bot/cash":
                    return {"items": [{"method": "cash", "currency": "KHR", "amount": "41000", "amount_usd": "10.00"},
                                      {"method": "KHQR", "currency": "USD", "amount": "5.00", "amount_usd": "5.00"}],
                            "total_usd": "15.00"}  # fmt: skip
                if path == "/bot/top":
                    return {"items": DAY["top"]}
                return {"count": 1, "soonest": [{"sku": "ORS", "lot_no": "L9", "qty_base": 20, "expiry_date": "2026-12-12",
                                                 "days_left": 46}]}  # fmt: skip

        self.client = Client

    def __call__(self, name: str):  # noqa: ANN204
        return self.client(name)


@pytest.fixture
def fakes(telegram, documents):  # noqa: ANN001, ANN201
    s = app.state.settings
    s.telegram_bot_username, s.telegram_webhook_secret = "pharma_test_bot", SECRET
    f = Fakes()
    old, bot.HOOKS = bot.HOOKS, Hooks(f)
    yield f
    bot.HOOKS = old
    s.telegram_bot_username, s.telegram_webhook_secret = "", ""


_n = iter(range(1, 10_000_000))


async def say(client, text: str, tg: str, chat: str | None = None, kind: str = "private") -> None:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/telegram/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": SECRET}, json={
        "update_id": next(_n), "message": {"message_id": next(_n), "chat": {"id": int(chat or tg), "type": kind},
                                           "from": {"id": int(tg)}, "text": text}})  # fmt: skip
    assert r.status_code == 200


async def link(client, user_id, tg: str, role: str = "branch_manager") -> None:  # noqa: ANN001
    headers = {**user(role, "x"), "X-User-Id": str(user_id)}
    token = (await client.post(f"{PREFIX}/me/telegram/link-token", headers=headers)).json()["url"].split("start=")[1]
    await say(client, f"/start {token}", tg)


def last(fake) -> str:  # noqa: ANN001
    return fake.sent[-1]["text"]


async def test_unlinked_and_unknown_chats_get_no_data(client, fakes, telegram) -> None:
    await say(client, "/today", "9001")
    assert "This is the pharmacy" in last(telegram) and fakes.asked == []
    await link(client, MGR_ID, MGR_TG)
    n = len(telegram.sent)
    await say(client, "/today", MGR_TG, chat="-100999", kind="group")  # a group nobody registered
    assert len(telegram.sent) == n and fakes.asked == []


async def test_answers_follow_branches_and_permissions(client, fakes, telegram) -> None:
    await link(client, MGR_ID, MGR_TG)
    await link(client, CASHIER_ID, CASHIER_TG, "cashier")
    await link(client, OWNER_ID, OWNER_TG, "owner")
    await say(client, "/today", MGR_TG)
    assert fakes.asked[-1] == ("/bot/day", {"day": "2026-10-27", "profit": "true", "branch_ids": str(PP1)})
    text = last(telegram)
    assert "Sales: 120.50 USD · 494,000 ៛" in text and "Gross profit: 40.10 USD" in text  # finance.cost_profit
    assert "First–last sale: 07:12–19:40" in text and "PARA500 30.00" in text
    await say(client, "/today", CASHIER_TG)
    assert last(telegram) == NO_PERMISSION
    await say(client, "/stock para", CASHIER_TG)  # inventory.view
    assert fakes.asked[-1] == ("/bot/stock", {"q": "para", "branch_ids": str(PP1)})
    assert last(telegram) == "📦 PARA500 Paracetamol: PP1 120 tablet"
    await say(client, "/branch PP2", MGR_TG)
    assert last(telegram) == NOT_YOURS
    await say(client, "/branch pp2", OWNER_TG)
    assert fakes.asked[-1][1]["branch_ids"] == str(PP2)
    await say(client, "/yesterday", OWNER_TG)
    assert fakes.asked[-1] == ("/bot/day", {"day": "2026-10-26", "profit": "true"})  # the owner: every branch
    await say(client, "/debtors", MGR_TG)
    assert "1. Sok Dara – 30.00 USD" in last(telegram)  # names in the private chat
    await say(client, "/help", CASHIER_TG)
    assert "/stock" in last(telegram) and "/today" not in last(telegram) and "/debtors" not in last(telegram)


async def test_group_chats_hide_cost_and_names_and_stay_on_their_branch(client, fakes, telegram) -> None:
    owner = user("owner", "*", ())
    for target, chat in ((str(PP1), "-1001"), (str(PP2), "-1003"), ("owner", "-1002")):
        await client.put(f"{PREFIX}/chats/{target}", json={"chat_id": chat, "is_active": True}, headers=owner)
    await link(client, MGR_ID, MGR_TG)
    await link(client, OWNER_ID, OWNER_TG, "owner")
    await say(client, "/today", MGR_TG, chat="-1001", kind="group")
    assert fakes.asked[-1] == ("/bot/day", {"day": "2026-10-27", "profit": "false", "branch_ids": str(PP1)})
    assert "Gross profit" not in last(telegram)
    await say(client, "/debtors", MGR_TG, chat="-1001", kind="group")
    assert fakes.asked[-1][1]["names"] == "false" and "Sok Dara" not in last(telegram) and "30.00 USD" in last(telegram)
    await say(client, "/today", MGR_TG, chat="-1003", kind="group")  # PP2's chat: not this manager's branch
    assert last(telegram) == NOT_YOURS
    await say(client, "/today", OWNER_TG, chat="-1003", kind="group")
    assert fakes.asked[-1][1] == {"day": "2026-10-27", "profit": "false", "branch_ids": str(PP2)}
    await say(client, "/today", OWNER_TG, chat="-1002", kind="group")  # the owner's chat: cost, every branch
    assert fakes.asked[-1][1] == {"day": "2026-10-27", "profit": "true"}
    await say(client, "/cash", OWNER_TG, chat="-1002", kind="group")
    assert "cash KHR: 41,000 ៛ (≈ 10.00 USD)" in last(telegram) and "Total: 15.00 USD" in last(telegram)


async def test_rate_limit_per_chat(client, fakes, telegram) -> None:
    await link(client, MGR_ID, MGR_TG)
    for _ in range(12):
        await say(client, "/top10", MGR_TG)
    replies = [x["text"] for x in telegram.sent if x["_method"] == "sendMessage"][1:]  # after the "linked" reply
    assert len([r for r in replies if r.startswith("🏆")]) == 10 and replies.count(SLOW) == 1
    assert len([p for p, _ in fakes.asked if p == "/bot/top"]) == 10


async def test_deactivated_staff_get_nothing(client, fakes, telegram) -> None:
    await link(client, MGR_ID, MGR_TG)
    fakes.access[str(MGR_ID)]["is_active"] = False
    n = len(telegram.sent)
    await say(client, "/today", MGR_TG)
    assert len(telegram.sent) == n and fakes.asked == []
