"""The staff side of the bot (bot.HOOKS): approval buttons (phase 2) and commands (phase 3).

Commands: /today, /yesterday, /branch <code>, /stock <name or barcode>, /expiring, /debtors, /cash, /top10, /help.
- Only from a linked staff Telegram user (My profile), in their private chat with the bot or in a registered owner /
  branch chat. Anyone else, and any other chat, gets no data.
- Answers follow the user's access right now (auth): their branches (the owner: all), the permission of each command
  (dashboard.view or reports.sales for figures, inventory.view for stock and expiry, contacts.customers or
  reports.customers for debtors). In a branch's chat only that branch, never cost or profit, never customer names;
  cost and profit only for finance.cost_profit (private chat or the owner's chat); customer names only in a private
  chat.
- At most commands_per_minute (10) answers per chat a minute; then one "slow down" and silence until it calms.
"""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError

from ..config import Settings
from ..models import KnownBranch, Message, TelegramChat
from . import approvals, links
from .telegram import Sender

COMMANDS = ("/today", "/yesterday", "/branch", "/stock", "/expiring", "/debtors", "/cash", "/top10", "/help")
NEEDS = {
    "/today": ("dashboard.view", "reports.sales"), "/yesterday": ("dashboard.view", "reports.sales"),
    "/branch": ("dashboard.view", "reports.sales"), "/top10": ("dashboard.view", "reports.sales"),
    "/cash": ("reports.sales",), "/stock": ("inventory.view",), "/expiring": ("inventory.view",),
    "/debtors": ("contacts.customers", "reports.customers"), "/help": (),
}  # fmt: skip
HELP = {
    "/today": ("លក់ថ្ងៃនេះ", "today's sales"), "/yesterday": ("លក់ម្សិលមិញ", "yesterday's sales"),
    "/branch": ("សាខាមួយ៖ /branch PP1", "one branch: /branch PP1"),
    "/stock": ("ស្តុក៖ /stock ឈ្មោះ ឬបាកូដ", "stock: /stock name or barcode"),
    "/expiring": ("ជិតផុតកំណត់", "expiring soon"), "/debtors": ("អតិថិជនជំពាក់ច្រើនជាងគេ", "top debtors"),
    "/cash": ("ប្រាក់តាមវិធីបង់ថ្ងៃនេះ", "today's money by method"), "/top10": ("ទំនិញលក់ដាច់ ១០", "top 10 today"),
    "/help": ("ជំនួយ", "this help"),
}  # fmt: skip
SLOW = "⏳ ពាក្យបញ្ជាច្រើនពេក សូមរង់ចាំមួយនាទី។ / Too many commands: wait a minute."
NOT_YOURS = "⛔ មិនមែនសាខារបស់អ្នក / Not one of your branches"
NO_PERMISSION = "⛔ អ្នកមិនមានសិទ្ធិ / You may not see this"


class Hooks:
    def __init__(self, clients: approvals.Clients | None = None) -> None:
        self._clients = clients

    def clients(self, settings: Settings) -> approvals.Clients:
        return self._clients or approvals.default_clients(settings)

    async def callback(self, session: AsyncSession, settings: Settings, sender: Sender, cb: dict[str, Any],
                       reply: Any) -> None:  # fmt: skip
        if str(cb.get("data") or "").startswith("ap:"):
            await approvals.tap(session, settings, sender, cb, self.clients(settings))

    async def command(self, session: AsyncSession, settings: Settings, command: str, arg: str, chat_id: str,
                      user_id: str, private: bool, reply: Any) -> bool:  # fmt: skip
        """True when the command was a staff command (answered or refused here)."""
        if command not in COMMANDS:
            return False
        link = await links.staff_link_of_user(session, user_id)
        group = None if private else (await session.execute(select(TelegramChat).where(
            TelegramChat.chat_id == chat_id, TelegramChat.is_active.is_(True)))).scalars().first()  # fmt: skip
        if link is None:
            return not private  # no data; a private chat then gets the customer's help or the greeting
        if not private and group is None:
            return True  # an unknown group: silence
        if await _too_many(session, settings, chat_id, reply):
            return True
        try:
            access = await self.clients(settings)("auth").get(f"/users/{link.subject_id}/access")
        except AppError:
            return True
        if not access.get("is_active"):
            return True
        where = "private" if private else ("owner" if group.target == "owner" else "branch")
        scope = Scope(access, where, None if where != "branch" else UUID(group.target))
        text = await answer(session, self.clients(settings)("reports"), command, arg, scope)
        await reply(text, "command_reply")
        return True


async def _too_many(session: AsyncSession, settings: Settings, chat_id: str, reply: Any) -> bool:
    since = clock.now() - timedelta(minutes=1)
    n = (await session.execute(select(func.count()).select_from(Message).where(
        Message.target == f"chat:{chat_id}", Message.kind == "command_reply", Message.next_attempt_at >= since))).scalar_one()  # fmt: skip
    if n < settings.commands_per_minute:
        return False
    told = (await session.execute(select(func.count()).select_from(Message).where(
        Message.target == f"chat:{chat_id}", Message.kind == "bot_reply", Message.text == SLOW,
        Message.next_attempt_at >= since))).scalar_one()  # fmt: skip
    if not told:
        await reply(SLOW)
    return True


class Scope:
    """What this person may see in this chat."""

    def __init__(self, access: dict[str, Any], where: str, chat_branch: UUID | None) -> None:
        self.perms = set(access.get("permissions") or [])
        self.owner = access.get("role") == "owner"
        self.where = where
        mine = None if self.owner else [UUID(str(b)) for b in access.get("branch_ids") or []]
        if chat_branch is not None:  # a branch's chat: that branch only (and only if it is theirs)
            mine = [chat_branch] if mine is None or chat_branch in mine else []
        self.branches = mine

    def may(self, command: str) -> bool:
        needs = NEEDS[command]
        return not needs or "*" in self.perms or bool(self.perms & set(needs))

    @property
    def profit(self) -> bool:
        return self.where != "branch" and ("*" in self.perms or "finance.cost_profit" in self.perms)

    @property
    def names(self) -> bool:
        return self.where == "private"

    def param(self, branches: list[UUID] | None = None) -> dict[str, str]:
        chosen = self.branches if branches is None else branches
        return {} if chosen is None else {"branch_ids": ",".join(str(b) for b in chosen)}


def _usd(v: Any) -> str:
    return f"{Decimal(str(v or 0)):,.2f}"


def _d(iso: str) -> str:
    y, m, d = iso[:10].split("-")
    return f"{d}/{m}/{y}"


def _label(branches: list[dict[str, Any]]) -> str:
    if len(branches) == 1:
        return f"{branches[0]['code']} {branches[0]['name_en']}"
    return f"{len(branches)} សាខា / {len(branches)} branches"


def day_text(r: dict[str, Any], which: tuple[str, str]) -> str:
    f = r["figures"]
    lines = [f"📊 {_label(r['branches'])} – {_d(r['day'])} ({which[0]} / {which[1]})",
             f"លក់ / Sales: {_usd(f['net_sales'])} USD · {int(f['net_sales_khr']):,} ៛",
             f"វិក្កយបត្រ / Invoices: {f['invoices']} · មធ្យម / avg {_usd(f['average_basket'])} USD",
             f"ប្រគល់វិញ / Returns: {_usd(f['returns'])} USD"]  # fmt: skip
    if "gross_profit" in f:
        lines.append(f"ចំណេញដុល / Gross profit: {_usd(f['gross_profit'])} USD ({f.get('margin_pct') or 0}%)")
    if r.get("first_sale"):
        lines.append(f"លក់ដំបូង–ចុងក្រោយ / First–last sale: {r['first_sale']}–{r['last_sale']}")
    if r.get("top"):
        lines.append("កំពូល / Top: " + ", ".join(f"{x['sku']} {_usd(x['net'])}" for x in r["top"]))
    return "\n".join(lines)


async def answer(session: AsyncSession, reports: Any, command: str, arg: str, scope: Scope) -> str:
    if command == "/help":
        allowed = [c for c in COMMANDS if scope.may(c)]
        return "\n".join(f"{c} – {HELP[c][0]} / {HELP[c][1]}" for c in allowed)
    if not scope.may(command):
        return NO_PERMISSION
    if scope.branches == []:
        return NOT_YOURS
    today = clock.today()
    if command in ("/today", "/yesterday", "/branch"):
        branches = None
        if command == "/branch":
            b = (await session.execute(select(KnownBranch).where(func.upper(KnownBranch.code) == arg.strip().upper())
                                       )).scalars().first()  # fmt: skip
            if b is None or (scope.branches is not None and b.id not in scope.branches):
                return NOT_YOURS
            branches = [b.id]
        on = today - timedelta(days=1) if command == "/yesterday" else today
        r = await reports.get("/bot/day", {"day": on.isoformat(), "profit": str(scope.profit).lower(),
                                           **scope.param(branches)})  # fmt: skip
        return day_text(r, ("ម្សិលមិញ", "yesterday") if command == "/yesterday" else ("ថ្ងៃនេះ", "today"))
    if command == "/top10":
        r = await reports.get("/bot/top", {"day": today.isoformat(), "n": "10", **scope.param()})
        if not r["items"]:
            return "🏆 មិនទាន់មានការលក់ថ្ងៃនេះ / No sales yet today"
        return "🏆 ទំនិញលក់ដាច់ថ្ងៃនេះ / Top 10 today\n" + "\n".join(
            f"{i}. {x['sku']} {x['name'] or ''} ×{x['qty_base']} · {_usd(x['net'])} USD" for i, x in enumerate(r["items"], 1))
    if command == "/cash":
        r = await reports.get("/bot/cash", {"day": today.isoformat(), **scope.param()})
        rows = []
        for x in r["items"]:
            if x["currency"] == "KHR":
                rows.append(f"• {x['method']} KHR: {int(Decimal(str(x['amount']))):,} ៛ (≈ {_usd(x['amount_usd'])} USD)")
            else:
                rows.append(f"• {x['method']} USD: {_usd(x['amount'])}")
        return "\n".join(["💵 ប្រាក់ថ្ងៃនេះ (ចូល − ចេញ) / Today's money (in − out)", *rows,
                          f"សរុប / Total: {_usd(r['total_usd'])} USD"])  # fmt: skip
    if command == "/stock":
        if not arg.strip():
            return "ប្រើ / Use: /stock ឈ្មោះ ឬបាកូដ / name or barcode"
        r = await reports.get("/bot/stock", {"q": arg.strip()[:60], **scope.param()})
        if not r["items"]:
            return "🔎 រកមិនឃើញ / Not found"
        return "\n".join(f"📦 {x['sku']} {x['name']}: " + (" · ".join(f"{b} {q}" for b, q in x["on_hand"].items()) or "0")
                         + f" {x['base_unit']}" for x in r["items"])  # fmt: skip
    if command == "/expiring":
        r = await reports.get("/bot/expiring", {"day": today.isoformat(), **scope.param()})
        lines = [f"⏳ ជិតផុតកំណត់ / Expiring soon: {r['count']}"]
        lines += [f"• {x['sku']} lot {x['lot_no']}: {x['qty_base']} – {_d(x['expiry_date'])} ({x['days_left']} d)"
                  for x in r.get("soonest") or []]  # fmt: skip
        return "\n".join(lines)
    r = await reports.get("/bot/debtors", {"n": "10", "names": str(scope.names).lower(), **scope.param()})
    items = r["items"]
    if not items:
        return "✅ គ្មានអតិថិជនជំពាក់ / No one owes anything"
    total = sum(Decimal(str(x["owes"])) for x in items)
    if not scope.names:  # a group chat: no customer names
        return f"🧾 អតិថិជនជំពាក់ / Debtors: {len(items)} · {_usd(total)} USD\n(ឈ្មោះ៖ ក្នុងការជជែកផ្ទាល់ / names: in a private chat)"
    return "🧾 អតិថិជនជំពាក់ច្រើនជាងគេ / Top debtors\n" + "\n".join(
        f"{i}. {x['customer']} – {_usd(x['owes'])} USD" for i, x in enumerate(items, 1))
