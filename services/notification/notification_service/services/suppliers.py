"""T2 phase 5: supplier chats. Rules:

- Staff with purchasing.order make a link for a supplier contact (Contacts → Supplier → Telegram; 7 days, once,
  private or group chat). A supplier may have several chats.
- purchase_order.sent → every linked chat of that supplier gets the PO PDF (rendered when sent) with a
  "Received / Confirmed" button. A tap from a chat linked to that supplier records the confirmation on the PO
  (purchasing, once) and edits the message with who and when; the branch's chat is told. Any other chat: refused.
- Texts carry the PO number, branch and expected date only (the PDF has the lines).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError

from ..config import Settings
from ..models import LinkToken, Message
from . import customer_texts as ct
from . import links
from .telegram import Sender, queue

CONFIRM = "✅ បានទទួល / បញ្ជាក់ · Received / Confirmed"


def _hm(at: datetime) -> str:
    return at.astimezone(clock.TIMEZONE).strftime("%d/%m %H:%M")


async def on_po_sent(session: AsyncSession, settings: Settings, po: dict[str, Any]) -> int:
    supplier = UUID((po.get("supplier") or {})["id"])
    branch = ct.branch_name(po.get("branch"), "km")
    made = 0
    for link in await links.active_links(session, "supplier", supplier):
        made += bool(await queue(
            session, settings, key=f"po:{po['purchase_order_id']}:{link.id}", target=f"supplier:{supplier}",
            chat_id=link.chat_id, kind="purchase_order", subject_id=supplier,
            branch_id=UUID(po["branch"]["id"]) if (po.get("branch") or {}).get("id") else None,
            text=ct.supplier_po("km", po["number"], branch, po.get("expected_on")) + "\n\n"
            + ct.supplier_po("en", po["number"], ct.branch_name(po.get("branch"), "en"), po.get("expected_on")),
            summary=f"PO {po['number']} → supplier {(po.get('supplier') or {}).get('code', '')} ({link.label or 'chat'})",
            document={"type": "purchase_order", "id": po["purchase_order_id"], "lang": "en"},
            reply_markup={"inline_keyboard": [[{"text": CONFIRM, "callback_data": f"po:{UUID(po['purchase_order_id']).hex}"}]]},
        ))  # fmt: skip
    return made


async def tap(session: AsyncSession, settings: Settings, sender: Sender, cb: dict[str, Any], purchasing: Any) -> None:
    answer = cb.get("id") or ""
    msg = cb.get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    try:
        po_id = UUID(hex=str(cb.get("data"))[3:])
    except ValueError:
        return
    sent = (await session.execute(select(Message).where(
        Message.kind == "purchase_order", Message.chat_id == chat_id, Message.dedupe_key.like(f"po:{po_id}:%")))
    ).scalars().first()  # fmt: skip
    link = next((x for x in await links.links_of_chat(session, chat_id)
                 if x.role == "supplier" and sent is not None and x.subject_id == sent.subject_id), None)  # fmt: skip
    if link is None:
        await sender.answer_callback(answer, "⛔ មិនអនុញ្ញាត / Not allowed", alert=True)
        return
    who = link.label or str((cb.get("from") or {}).get("first_name") or "supplier")
    try:
        r = await purchasing.post(f"/purchase-orders/{po_id}/supplier-confirm", {"supplier_id": str(link.subject_id),
                                                                               "by": who})  # fmt: skip
    except AppError as exc:
        await sender.answer_callback(answer, exc.message[:190], alert=True)
        return
    at = datetime.fromisoformat(r["supplier_confirmed_at"])
    line = f"✅ បានបញ្ជាក់ដោយ {r['supplier_confirmed_by']} · {_hm(at)} / Confirmed by {r['supplier_confirmed_by']} · {_hm(at)}"
    if sent.tg_message_id:
        await queue(session, settings, key=f"po_confirmed:{po_id}:{chat_id}", target=f"chat:{chat_id}",
                    kind="approval_done", text=f"🛒 {r['number']}\n{line}", method="caption",
                    edit_message_id=sent.tg_message_id, reply_markup={"inline_keyboard": []})  # fmt: skip
    if sent.branch_id:
        await queue(session, settings, key=f"po_confirmed_branch:{po_id}", target=str(sent.branch_id), kind="ops",
                    text=f"🛒 {r['number']}: {line}", branch_id=sent.branch_id)  # fmt: skip
    await sender.answer_callback(answer, "✅")


# ------------------------------------------------------------------ staff side (Contacts → Supplier)


def _need(user: CurrentUser) -> None:
    if not user.has_any("purchasing.order", "contacts.suppliers"):
        user.require("purchasing.order")


async def status(session: AsyncSession, settings: Settings, user: CurrentUser, supplier_id: UUID) -> dict[str, Any]:
    _need(user)
    rows = await links.active_links(session, "supplier", supplier_id)
    return {"supplier_id": supplier_id, "links": [{"id": r.id, "via": r.via, "label": r.label, "linked_at": r.linked_at}
                                                  for r in rows],
            "bot_configured": bool(settings.telegram_bot_token and settings.telegram_bot_username)}  # fmt: skip


async def link_token(session: AsyncSession, settings: Settings, user: CurrentUser, supplier_id: UUID, label: str) -> dict[str, Any]:
    user.require("purchasing.order")
    ref = f"supplier:{supplier_id}:{label.strip().lower()[:40]}"
    token = await links.issue(session, settings, role="supplier", subject_id=supplier_id, ref=ref, via="supplier",
                              phone_check=False, label=label.strip()[:80], created_by=user.id)  # fmt: skip
    row = await session.get(LinkToken, links.token_hash(token))
    await session.commit()
    return {"url": links.deep_link(settings, token), "expires_at": row.expires_at}


async def unlink(session: AsyncSession, user: CurrentUser, supplier_id: UUID, link_id: UUID) -> None:
    user.require("purchasing.order")
    await links.unlink_subject(session, "supplier", supplier_id, user, link_id)
    await session.commit()
