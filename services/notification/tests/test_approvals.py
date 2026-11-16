"""T2 phase 2: approval buttons – who may tap (linked staff, current access, branch, limits), only the first decision
counts, messages edited with who and when, decided in the app, controlled / PIN / above the limit only in the app."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from notification_service.db import db
from notification_service.main import app
from notification_service.models import Approval, Message
from notification_service.services import bot
from notification_service.services.staff_bot import Hooks
from pharmacy_shared.errors import AppError, ErrorCode

from .conftest import PP1, PP2, PREFIX, event, messages, sender, user

SECRET = "w" * 40
MGR_ID, OWNER_ID, CASHIER_ID, MGR2_ID = uuid4(), uuid4(), uuid4(), uuid4()
MGR_TG, OWNER_TG, CASHIER_TG, MGR2_TG = "7001", "7002", "7003", "7004"
APPROVE = "inventory.shrinkage_approve,stockcount.approve,transfers.approve,purchasing.request_approve,sales.discount"


class Fakes:
    """auth's /users/{id}/access and the owning services' /decide."""

    def __init__(self) -> None:
        self.access = {
            str(MGR_ID): {"user_id": str(MGR_ID), "name": "Dara", "role": "branch_manager", "is_active": True,
                          "branch_ids": [str(PP1)], "permissions": [*APPROVE.split(","), "notifications.approve_via_telegram"]},
            str(OWNER_ID): {"user_id": str(OWNER_ID), "name": "Owner Sok", "role": "owner", "is_active": True,
                            "branch_ids": [], "permissions": ["*"]},
            str(CASHIER_ID): {"user_id": str(CASHIER_ID), "name": "Cashier", "role": "cashier", "is_active": True,
                              "branch_ids": [str(PP1)], "permissions": ["pos.sell"]},
            str(MGR2_ID): {"user_id": str(MGR2_ID), "name": "Other", "role": "branch_manager", "is_active": True,
                           "branch_ids": [str(PP2)], "permissions": [*APPROVE.split(","), "notifications.approve_via_telegram"]},
        }  # fmt: skip
        self.posts: list[tuple[str, str, dict]] = []
        self.errors: list[AppError] = []
        outer = self

        class Client:
            def __init__(self, name: str) -> None:
                self.name = name

            async def get(self, path: str, params: dict | None = None, **_: object) -> dict:
                assert self.name == "auth"
                return outer.access[path.split("/")[2]]

            async def post(self, path: str, body: dict, **_: object) -> dict:
                outer.posts.append((self.name, path, body))
                if outer.errors:
                    raise outer.errors.pop(0)
                return {"status": "ok"}

        self.client = Client

    def __call__(self, name: str):  # noqa: ANN204
        return self.client(name)


@pytest.fixture
def fakes(telegram, documents):  # noqa: ANN001, ANN201
    s = app.state.settings
    s.telegram_bot_username, s.telegram_webhook_secret, s.service_token = "pharma_test_bot", SECRET, "s" * 40
    f = Fakes()
    old, bot.HOOKS = bot.HOOKS, Hooks(f)
    yield f
    bot.HOOKS = old
    s.telegram_bot_username, s.telegram_webhook_secret, s.service_token = "", "", ""


_n = iter(range(1, 10_000_000))


async def hook(client, update: dict):  # noqa: ANN001, ANN201
    r = await client.post(f"{PREFIX}/telegram/webhook", json={"update_id": next(_n), **update},
                          headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})  # fmt: skip
    assert r.status_code == 200, r.text
    return r


async def link_staff(client, user_id: UUID, tg: str, role: str = "branch_manager") -> None:  # noqa: ANN001
    headers = {**user(role, "notifications.manage"), "X-User-Id": str(user_id)}
    r = await client.post(f"{PREFIX}/me/telegram/link-token", headers=headers)
    token = r.json()["url"].split("start=")[1]
    assert token.startswith("s")
    await hook(client, {"message": {"message_id": 1, "chat": {"id": int(tg), "type": "private"}, "from": {"id": int(tg)},
                                    "text": f"/start {token}"}})  # fmt: skip
    assert (await client.get(f"{PREFIX}/me/telegram", headers=headers)).json()["linked"] is True


async def chats(client) -> None:  # noqa: ANN001
    owner = user("owner", "*", ())
    for target, chat in ((str(PP1), "-1001"), ("owner", "-1002")):
        await client.put(f"{PREFIX}/chats/{target}", json={"chat_id": chat, "is_active": True}, headers=owner)


async def shrinkage(value: str = "30.00", controlled: bool = False, ref: UUID | None = None) -> UUID:
    ref = ref or uuid4()
    await event("shrinkage.created", {"shrinkage_id": str(ref), "number": "PP1-SH-2026-000012", "branch_id": str(PP1),
                                      "lot_no": "L1", "qty_base": 20, "reason": "damaged", "value": value,
                                      "status": "pending_approval", "is_controlled": controlled,
                                      "created_by": str(CASHIER_ID)})  # fmt: skip
    return ref


async def approval(ref: UUID) -> Approval:
    async with db.sessionmaker() as s:
        return (await s.execute(select(Approval).where(Approval.ref_id == ref))).scalar_one()


async def send_all() -> None:
    async with db.sessionmaker() as s:
        await sender().send_due(s)


def tap(a: Approval, tg: str, act: str = "a", chat: str = "-1001") -> dict:
    return {"callback_query": {"id": f"cb{next(_n)}", "data": f"ap:{a.id.hex}:{act}", "from": {"id": int(tg)},
                               "message": {"message_id": 5, "chat": {"id": int(chat), "type": "group"}}}}  # fmt: skip


def answers(fake) -> list[str]:  # noqa: ANN001
    return [c["text"] for c in fake.calls if c["_method"] == "answerCallbackQuery"]


async def test_buttons_go_to_branch_and_owner_with_cost_only_for_the_owner(client, fakes, telegram) -> None:
    await chats(client)
    ref = await shrinkage("30.00")
    rows = {m.target: m for m in await messages() if m.kind == "approval"}
    assert set(rows) == {str(PP1), "owner"}
    assert "Value: 30.00 USD" in rows["owner"].text and "30.00" not in rows[str(PP1)].text
    assert "Shrinkage PP1-SH-2026-000012 by staff" in rows[str(PP1)].text and "ការកាត់ចេញពីស្តុក" in rows[str(PP1)].text
    buttons = rows[str(PP1)].reply_markup["inline_keyboard"][0]
    a = await approval(ref)
    assert [b["callback_data"] for b in buttons] == [f"ap:{a.id.hex}:a", f"ap:{a.id.hex}:r"]
    await event("shrinkage.created", {"shrinkage_id": str(ref), "branch_id": str(PP1), "status": "pending_approval",
                                      "value": "30.00"})  # a replay: nothing new  # fmt: skip
    assert len([m for m in await messages() if m.kind == "approval"]) == 2


async def test_first_tap_decides_edits_every_message_and_a_second_tap_only_shows_it(client, fakes, telegram) -> None:
    await chats(client)
    await link_staff(client, MGR_ID, MGR_TG)
    await link_staff(client, OWNER_ID, OWNER_TG, "owner")
    ref = await shrinkage("30.00")
    await send_all()
    a = await approval(ref)
    await hook(client, tap(a, MGR_TG))
    assert fakes.posts == [("inventory", f"/shrinkages/{ref}/decide", {
        "decision": "approve", "actor": {**fakes.access[str(MGR_ID)], "is_pharmacist": False},
        "reason": "Rejected on Telegram by Dara"})]  # fmt: skip
    a = await approval(ref)
    assert (a.status, a.decided_name, a.decided_via) == ("approved", "Dara", "telegram")
    await send_all()
    edits = [x for x in telegram.sent if x["_method"] == "editMessageText"]
    assert len(edits) == 2 and all("Approved by Dara" in e["text"] and "(Telegram)" in e["text"] for e in edits)
    assert all(e["reply_markup"] == {"inline_keyboard": []} for e in edits)
    await hook(client, tap(a, OWNER_TG, "r", "-1002"))  # the owner taps reject a moment later
    assert len(fakes.posts) == 1 and "Approved by Dara" in answers(telegram)[-1]


async def test_who_may_not_tap(client, fakes, telegram) -> None:
    await chats(client)
    ref = await shrinkage("30.00")
    a = await approval(ref)
    await hook(client, tap(a, "9999"))  # Telegram user not linked to staff
    assert "link your Telegram" in answers(telegram)[-1]
    await link_staff(client, CASHIER_ID, CASHIER_TG, "cashier")
    await hook(client, tap(a, CASHIER_TG))
    assert answers(telegram)[-1].endswith("permission")
    await link_staff(client, MGR2_ID, MGR2_TG)
    await hook(client, tap(a, MGR2_TG))  # a manager of another branch
    assert answers(telegram)[-1].endswith("branch")
    await link_staff(client, MGR_ID, MGR_TG)
    fakes.access[str(MGR_ID)]["permissions"].remove("notifications.approve_via_telegram")  # revoked since linking
    await hook(client, tap(a, MGR_TG))
    assert answers(telegram)[-1].endswith("permission") and fakes.posts == []
    assert (await approval(ref)).status == "pending"


async def test_controlled_pin_and_above_the_limit_only_in_the_app(client, fakes, telegram) -> None:
    await chats(client)
    await link_staff(client, OWNER_ID, OWNER_TG, "owner")
    ctl = await shrinkage("10.00", controlled=True)
    big = await shrinkage("150.00")
    for ref, why in ((ctl, "controlled medicine"), (big, "above the Telegram limit")):
        rows = [m for m in await messages() if m.kind == "approval" and m.subject_id == (await approval(ref)).id]
        assert len(rows) == 2 and all(m.reply_markup is None for m in rows), "no buttons"
        assert all(f"{why} – open in the app" in m.text for m in rows)
    await hook(client, tap(await approval(ctl), OWNER_TG, chat="-1002"))  # a forged button
    assert answers(telegram)[-1].endswith("open the app") and fakes.posts == []
    r = await client.put(f"{PREFIX}/settings", headers=user("owner", "*", ()), json={
        "large_discount_pct": "20", "large_discount_usd": "10", "telegram_approval_max_usd": "200"})  # fmt: skip
    assert Decimal(r.json()["telegram_approval_max_usd"]) == Decimal("200")
    big2 = await shrinkage("150.00")
    assert (await approval(big2)).telegram_ok is True
    app.state.settings.web_url = "https://pharmacy.example.com"
    try:
        ctl2 = await shrinkage("10.00", controlled=True)
        ctl2_id = (await approval(ctl2)).id
        row = next(m for m in await messages() if m.subject_id == ctl2_id)
        assert row.reply_markup == {"inline_keyboard": [[{"text": "📱 បើកក្នុងកម្មវិធី / Open in app",
                                                          "url": "https://pharmacy.example.com/approvals"}]]}  # fmt: skip
    finally:
        app.state.settings.web_url = "http://localhost"


async def test_owner_only_goes_to_the_owner_and_a_manager_is_refused(client, fakes, telegram) -> None:
    await chats(client)
    await link_staff(client, MGR_ID, MGR_TG)
    ref = uuid4()
    await event("count.submitted", {"count_id": str(ref), "number": "PP1-SC-2026-000003", "branch_id": str(PP1),
                                    "variance_value": "80.00", "needs_owner": True, "needs_pin": False,
                                    "lines": [{"is_controlled": False}], "submitted_by": str(CASHIER_ID)})  # fmt: skip
    a = await approval(ref)
    assert [m.target for m in await messages() if m.subject_id == a.id] == ["owner"]
    assert len(next(m for m in await messages() if m.subject_id == a.id).reply_markup["inline_keyboard"][0]) == 1  # no reject
    await hook(client, tap(a, MGR_TG, chat="-1002"))
    assert answers(telegram)[-1].endswith("owner only")


async def test_decided_in_the_app_edits_the_messages(client, fakes, telegram) -> None:
    await chats(client)
    await event("user.created", {"user_id": str(MGR_ID), "name": "Dara", "branch_ids": [str(PP1)]})
    ref = await shrinkage("30.00")
    await send_all()
    await event("shrinkage.approved", {"shrinkage_id": str(ref), "status": "posted", "decided_by": str(MGR_ID)})
    a = await approval(ref)
    assert (a.status, a.decided_name, a.decided_via) == ("approved", "Dara", "app")
    await send_all()
    edits = [x for x in telegram.sent if x["_method"] == "editMessageText"]
    assert len(edits) == 2 and "Approved by Dara" in edits[0]["text"] and "in the app" in edits[0]["text"]


async def test_service_says_already_decided_then_the_buttons_go(client, fakes, telegram) -> None:
    await chats(client)
    await link_staff(client, MGR_ID, MGR_TG)
    ref = await shrinkage("30.00")
    fakes.errors.append(AppError(ErrorCode.SHRINKAGE_STATE, "This shrinkage is posted", status_code=409))
    await hook(client, tap(await approval(ref), MGR_TG))
    assert answers(telegram)[-1] == "This shrinkage is posted" and (await approval(ref)).status == "closed"
    rows = [m for m in await messages() if m.kind == "approval"]
    assert all(m.reply_markup is None and "Closed" in m.text for m in rows)  # not sent yet: go out decided
    fakes.errors.append(AppError(ErrorCode.FORBIDDEN, "Someone else must approve your own shrinkage", status_code=403))
    ref2 = await shrinkage("30.00")
    await hook(client, tap(await approval(ref2), MGR_TG))
    assert (await approval(ref2)).status == "pending"  # a rule of the service: nothing decided


async def test_every_kind_reaches_its_service(client, fakes, telegram) -> None:
    await chats(client)
    await link_staff(client, OWNER_ID, OWNER_TG, "owner")
    tr, pr, disc = uuid4(), uuid4(), uuid4()
    await event("transfer_request.created", {"request_id": str(tr), "number": "PP2-TQ-2026-000001", "status": "requested",
                                             "from_branch_id": str(PP1), "to_branch_id": str(PP2), "value": "12.00",
                                             "has_controlled": False, "lines": [{}]})  # fmt: skip
    await event("purchase_request.created", {"request_id": str(pr), "number": "PP1-PR-2026-000001", "status": "submitted",
                                             "branch_id": str(PP1), "value": "40.00", "has_controlled": False,
                                             "lines": [{}, {}]})  # fmt: skip
    await event("discount_approval.requested", {"approval_id": str(disc), "branch_id": str(PP1), "seller_id": str(CASHIER_ID),
                                                "worst_pct": "15.00", "cap_pct": "5.00", "discount_usd": "3.00",
                                                "total_usd": "17.00", "needs_owner": False})  # fmt: skip
    rows = {m.subject_id: m for m in await messages() if m.kind == "approval" and m.target == str(PP1)}
    disc_msg = rows[(await approval(disc)).id]
    assert "Discount: 3.00 USD" in disc_msg.text  # a discount amount is not a cost: shown in the branch chat too
    for ref, act in ((tr, "a"), (pr, "r"), (disc, "a")):
        await hook(client, tap(await approval(ref), OWNER_TG, act, "-1002"))
    assert [(s, p, b["decision"]) for s, p, b in fakes.posts] == [
        ("inventory", f"/transfer-requests/{tr}/decide", "approve"), ("purchasing", f"/purchase-requests/{pr}/decide", "reject"),
        ("sales", f"/discount-approvals/{disc}/decide", "approve")]  # fmt: skip
    unknown = uuid4()
    await event("purchase_request.created", {"request_id": str(unknown), "status": "submitted", "branch_id": str(PP1),
                                             "value": None, "lines": [{}]})  # never received: value unknown  # fmt: skip
    assert (await approval(unknown)).telegram_ok is False


async def test_staff_link_token_lasts_15_minutes_and_unlink(client, fakes) -> None:
    headers = {**user("branch_manager", "notifications.manage"), "X-User-Id": str(MGR_ID)}
    r = (await client.post(f"{PREFIX}/me/telegram/link-token", headers=headers)).json()
    assert r["url"].startswith("https://t.me/pharma_test_bot?start=s")
    await link_staff(client, MGR_ID, MGR_TG)
    r = (await client.post(f"{PREFIX}/me/telegram/unlink", headers=headers)).json()
    assert r["linked"] is False
    async with db.sessionmaker() as s:
        row = (await s.execute(select(Message).where(Message.kind == "bot_reply"))).scalars().first()
        assert "Staff account linked" in row.text
