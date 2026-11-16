"""The Telegram link printed on receipts, A4 invoices and statements (T2).

Only for a customer who is not linked yet; the notification service decides
(/internal/v1/link-tokens) and gives the same link for the same document while it is
unused. Any problem (service down, slow, bot not set up) → no QR: printing never
waits for Telegram.
"""

import logging
from collections.abc import Awaitable, Callable
from html import escape as e
from typing import Any

from pharmacy_shared.errors import AppError
from pharmacy_shared.internal import InternalClient

from .transfer_note import qr_data_uri

log = logging.getLogger(__name__)
LinkFor = Callable[[str, str, str], Awaitable[str | None]]  # (customer_id, ref, via) → url

TEXT = {"km": ("ទទួលបង្កាន់ដៃ និងការរំលឹកតាម Telegram", "ស្កេន QR"),
        "en": ("Get receipts and reminders on Telegram", "Scan the QR")}  # fmt: skip


def link_getter(notification: InternalClient | None) -> LinkFor | None:
    if notification is None:
        return None

    async def get(customer_id: str, ref: str, via: str) -> str | None:
        try:
            out: dict[str, Any] = await notification.post("/link-tokens", {"customer_id": customer_id, "ref": ref,
                                                                           "via": via})  # fmt: skip
        except AppError as exc:
            log.info("telegram link skipped: %s", exc.code)
            return None
        except Exception:  # noqa: BLE001 – a receipt is never refused because of Telegram
            log.info("telegram link skipped: notification did not answer")
            return None
        return out.get("url")

    return get


def block(url: str | None, lang: str, size_mm: int = 22) -> str:
    if not url:
        return ""
    line, scan = TEXT.get(lang, TEXT["km"])
    return (f'<div class="c small tg" style="margin-top:2mm;text-align:center">'
            f'<img src="{qr_data_uri(url)}" style="width:{size_mm}mm;height:{size_mm}mm" alt="Telegram">'
            f"<div>{e(line)}</div><div>{e(scan)} · Telegram</div></div>")  # fmt: skip
