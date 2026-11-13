"""Receipts (80 mm roll) and A4 invoices, printed from the copy of invoice.*
events. Rules:

- Needs pos.sell or sales.view and access to the invoice's branch (others: 404).
- Right after the sale its event may still be on its way: wait up to 5 s, then
  DOCUMENT_NOT_READY (409).
- Shows the branch name (Khmer and English) with the receipt header and footer
  from the branch settings, lines, the total in USD and in KHR at the rate the
  sale used, the payments, and the change given in USD + KHR.
- A cancelled invoice is printed with a CANCELLED mark; returns are listed.
- The 80 mm receipt is as long as its content: laid out once on a long page,
  measured, then printed on a page cut to that length.
- Rx lines show the prescription number and the lot(s) with expiry.
- T2: a customer not linked to Telegram yet gets a QR (t.me link, once, 7 days) under
  the footer; the customer must then share the phone number on the record.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser

from ..models import InvoiceCopy
from . import telegram_link
from .pdf import FONTS, e, html_to_pdf
from .stored import upsert_versioned, wait_for

INVOICE_EVENTS = frozenset({"invoice.created", "invoice.cancelled", "invoice.returned"})
METHODS = {"cash": "Cash", "card": "Card", "ABA": "Bank transfer", "KHQR": "KHQR", "PAYWAY": "Card / Wallet (PayWay)",
           "credit": "On credit"}  # fmt: skip
PX_TO_MM = 25.4 / 96


async def upsert_invoice(session: AsyncSession, payload: dict[str, Any]) -> bool:
    return await upsert_versioned(session, InvoiceCopy, {
        "id": UUID(str(payload["invoice_id"])), "version": int(payload["version"]),
        "branch_id": UUID(str(payload["branch"]["id"])), "number": payload.get("number"),
        "status": str(payload["status"]), "data": payload})  # fmt: skip


def _usd(value: str | Decimal) -> str:
    return f"{Decimal(str(value)):,.2f}"


def _riel(value: int | None) -> str:
    return f"{value:,}" if value is not None else "–"


def _when(inv: dict[str, Any]) -> str:
    if not inv.get("completed_at"):
        return ""
    return datetime.fromisoformat(inv["completed_at"]).astimezone(clock.TIMEZONE).strftime("%Y-%m-%d %H:%M")


def _multiline(text: str | None) -> str:
    return "<br>".join(e(x) for x in (text or "").splitlines())


def _payments(inv: dict[str, Any]) -> list[tuple[str, str]]:
    rows = []
    for p in inv["payments"]:
        amount = (
            f"{_riel(int(Decimal(p['amount'])))} ៛" if p["currency"] == "KHR" else f"${_usd(p['amount'])}"
        )
        label = METHODS.get(p["method"], p["method"])
        rows.append((f"{label} · {p['reference']}" if p.get("reference") else label, amount))  # escaped when drawn
    return rows


def _change(inv: dict[str, Any]) -> str:
    parts = []
    if Decimal(inv["change_given_usd"]) > 0:
        parts.append(f"${_usd(inv['change_given_usd'])}")
    if inv["change_given_khr"]:
        parts.append(f"{_riel(inv['change_given_khr'])} ៛")
    return " + ".join(parts) or "0"


def _receipt_item(x: dict[str, Any]) -> str:
    km = f"<div class='km' lang='km'>{e(x['name_km'])}</div>" if x["name_km"] else ""
    if x.get("rx"):
        lots = ", ".join(f"{b['lot_no']} exp {b['expiry_date']}" for b in x.get("batches") or [])
        km += f"<div class='small'>Rx {e(x['rx']['prescription_number'])} · Lot {e(lots)}</div>"
    return (
        f"<div class='item'><div class='name'>{e(x['name'])}</div>{km}"
        f"<div class='row'><span>{x['qty']} {e(x['pack_unit'])} × {_usd(x['unit_price'])}</span>"
        f"<span>{_usd(x['line_total'])}</span></div></div>"
    )


T = {  # labels of the receipt and the A4 invoice; numbers, SKUs and names are not translated
    "en": {"receipt": "Receipt", "customer": "Customer", "total": "Total", "total_khr": "Total (KHR)",
           "change": "Change", "credit": "On credit", "returned": "Returned", "cancelled": "CANCELLED",
           "invoice": "INVOICE", "item": "Item", "pack": "Pack", "qty": "Qty", "price": "Price (USD)",
           "amount": "Amount (USD)", "total_usd": "Total USD", "rate": "Rate"},
    "km": {"receipt": "បង្កាន់ដៃ", "customer": "អតិថិជន", "total": "សរុប", "total_khr": "សរុប (រៀល)",
           "change": "ប្រាក់អាប់", "credit": "ជំពាក់", "returned": "បានប្តូរយកវិញ", "cancelled": "បានលុបចោល",
           "invoice": "វិក្កយបត្រ", "item": "មុខទំនិញ", "pack": "ខ្នាត", "qty": "ចំនួន", "price": "តម្លៃ (USD)",
           "amount": "ទឹកប្រាក់ (USD)", "total_usd": "សរុប (USD)", "rate": "អត្រាប្តូរប្រាក់"},
}  # fmt: skip


def lang_of(inv: dict[str, Any], lang: str | None) -> str:
    """Asked, else the branch setting receipt_lang (in the invoice), else Khmer."""
    chosen = lang or (inv.get("branch") or {}).get("receipt_lang") or "km"
    return chosen if chosen in T else "km"


def receipt_html(inv: dict[str, Any], page_height_mm: float = 2000, lang: str = "km", tg_url: str | None = None) -> str:
    t = T[lang]
    b = inv["branch"]
    lines = "".join(_receipt_item(x) for x in inv["lines"])
    pays = "".join(
        f"<div class='row'><span>{e(m)}</span><span>{e(a)}</span></div>" for m, a in _payments(inv)
    )
    customer = inv.get("customer")
    cust = f"<div>{t['customer']}: {e(customer['name'])} {e(customer['phone'])}</div>" if customer else ""
    credit = (f"<div class='row'><span>{t['credit']}</span><span>${_usd(inv['credit_amount'])}</span></div>"
              if Decimal(inv["credit_amount"]) > 0 else "")  # fmt: skip
    rate = f"<div class='small'>1 USD = {_riel(inv['khr_per_usd'])} ៛</div>" if inv.get("khr_per_usd") else ""
    cancelled = f"<div class='stamp'>{t['cancelled']}</div>" if inv["status"] == "cancelled" else ""
    returns = "".join(f"<div class='row small'><span>{t['returned']} {e(r['number'])}</span>"
                      f"<span>-${_usd(r['refund_usd'])}</span></div>" for r in inv.get("returns") or [])  # fmt: skip
    css = f"""
      @page {{ size: 80mm {page_height_mm:.1f}mm; margin: 3mm 3.5mm }}
      * {{ box-sizing: border-box; margin: 0 }}
      body {{ font-family: {FONTS}; font-size: 8.5pt; color: #000; line-height: 1.3 }}
      .c {{ text-align: center }} h1 {{ font-size: 11pt }} .km {{ font-size: 8.5pt }}
      .small {{ font-size: 7.5pt }} hr {{ border: 0; border-top: 0.3mm dashed #000; margin: 1.5mm 0 }}
      .row {{ display: flex; justify-content: space-between; gap: 2mm }}
      .item {{ margin-bottom: 1mm }} .name {{ font-weight: 700 }}
      .total {{ font-size: 11pt; font-weight: 700 }}
      .stamp {{ border: 0.5mm solid #000; text-align: center; font-weight: 700; margin: 1mm 0; padding: 0.5mm }}
    """
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>{css}</style></head><body>
      <div id="receipt">
      <div class="c"><h1>{e(b["name_en"])}</h1><div class="km" lang="km">{e(b["name_km"])}</div>
        <div class="small">{_multiline(b.get("receipt_header"))}</div></div>
      <hr>
      <div class="row"><span>{t["receipt"]}</span><b>{e(inv.get("number"))}</b></div>
      <div class="small">{e(_when(inv))}</div>{cust}{cancelled}
      <hr>{lines}<hr>
      <div class="row total"><span>{t["total"]}</span><span>${_usd(inv["total"])}</span></div>
      <div class="row"><span>{t["total_khr"]}</span><span>{_riel(inv.get("total_khr"))} ៛</span></div>{rate}
      <hr>{pays}{credit}
      <div class="row"><span>{t["change"]}</span><b>{e(_change(inv))}</b></div>{returns}
      <hr><div class="c small">{_multiline(b.get("receipt_footer"))}</div>{telegram_link.block(tg_url, lang)}
      </div></body></html>"""


def _render_receipt(inv: dict[str, Any], lang: str = "km", tg_url: str | None = None) -> bytes:
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher

    fetcher = URLFetcher(allowed_protocols={"data"})
    page = HTML(string=receipt_html(inv, lang=lang, tg_url=tg_url), url_fetcher=fetcher).render().pages[0]
    bottom = max(
        (b.position_y + b.margin_height() for b in page._page_box.descendants()
         if getattr(b, "element_tag", None) == "div" and hasattr(b, "margin_height")),
        default=200,
    )  # fmt: skip
    height = bottom * PX_TO_MM + 3 + 6  # bottom page margin + a little to tear off
    return HTML(string=receipt_html(inv, height, lang, tg_url), url_fetcher=fetcher).write_pdf()


def invoice_a4_html(inv: dict[str, Any], lang: str = "km", tg_url: str | None = None) -> str:
    t = T[lang]
    b, customer = inv["branch"], inv.get("customer")
    rows = "".join(
        f"<tr><td>{x['line_no']}</td><td><b>{e(x['name'])}</b><div class='km' lang='km'>{e(x['name_km'])}</div>"
        f"<div class='sub'>{e(x['sku'])}</div></td><td>{e(x['pack_unit'])}</td><td class='r'>{x['qty']}</td>"
        f"<td class='r'>{_usd(x['unit_price'])}</td><td class='r'>{_usd(x['line_total'])}</td></tr>"
        for x in inv["lines"]
    )
    pays = "".join(f"<div>{e(m)}: {e(a)}</div>" for m, a in _payments(inv))
    watermark = f"<div class='watermark'>{t['cancelled']}</div>" if inv["status"] == "cancelled" else ""
    css = f"""
      @page {{ size: A4; margin: 14mm 12mm }}
      * {{ box-sizing: border-box }} body {{ font-family: {FONTS}; font-size: 9.5pt; color: #111 }}
      h1 {{ font-size: 15pt; margin: 0 }} .km {{ font-size: 9pt }} .sub {{ font-size: 7.5pt; color: #555 }}
      .head {{ display: flex; justify-content: space-between; border-bottom: 0.4mm solid #000; padding-bottom: 3mm }}
      .right {{ text-align: right }} .number {{ font-size: 12pt; font-weight: 700 }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 4mm }}
      th {{ text-align: left; font-size: 8pt; border-bottom: 0.3mm solid #000; padding: 1.5mm 1mm }}
      td {{ border-bottom: 0.2mm solid #ccc; padding: 1.5mm 1mm; vertical-align: top }} .r {{ text-align: right }}
      .totals {{ margin-left: auto; width: 75mm; margin-top: 3mm }}
      .totals div {{ display: flex; justify-content: space-between }} .big {{ font-size: 12pt; font-weight: 700 }}
      .watermark {{ position: fixed; top: 110mm; left: 0; right: 0; text-align: center; font-size: 72pt;
                    color: rgba(0,0,0,0.08); transform: rotate(-25deg); font-weight: 700 }}
    """
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>{css}</style></head><body>
      {watermark}
      <div class="head"><div><h1>{e(b["name_en"])}</h1><div class="km" lang="km">{e(b["name_km"])}</div>
        <div class="sub">{_multiline(b.get("receipt_header"))}</div></div>
        <div class="right"><div class="sub">{t["invoice"]}</div><div class="number">{
        e(inv.get("number"))
    }</div>
        <div>{e(_when(inv))}</div></div></div>
      {f"<p>{t['customer']}: <b>{e(customer['name'])}</b> {e(customer['phone'])}</p>" if customer else ""}
      <table><thead><tr><th>#</th><th>{t["item"]}</th><th>{t["pack"]}</th><th class="r">{t["qty"]}</th>
        <th class="r">{t["price"]}</th><th class="r">{t["amount"]}</th></tr></thead><tbody>{rows}</tbody></table>
      <div class="totals">
        <div class="big"><span>{t["total_usd"]}</span><span>{_usd(inv["total"])}</span></div>
        <div><span>{t["total_khr"]}</span><span>{_riel(inv.get("total_khr"))} ៛</span></div>
        {
        f"<div class='sub'><span>{t['rate']}</span><span>1 USD = {_riel(inv['khr_per_usd'])} ៛</span></div>"
        if inv.get("khr_per_usd")
        else ""
    }
        <div><span>{t["change"]}</span><span>{e(_change(inv))}</span></div>
      </div>
      <div style="margin-top:4mm">{pays}</div>
      <p class="sub" style="margin-top:8mm">{_multiline(b.get("receipt_footer"))}</p>
      {telegram_link.block(tg_url, lang, 26)}
    </body></html>"""


async def render(
    session: AsyncSession, actor: CurrentUser, invoice_id: UUID, kind: str, wait_seconds: float,
    lang: str | None = None, link_for: telegram_link.LinkFor | None = None,
) -> tuple[str, bytes]:
    """link_for: the Telegram QR for a customer not linked yet (T2); None = no QR (e.g. the copy sent on
    Telegram itself)."""
    inv = await wait_for(session, InvoiceCopy, invoice_id, actor, wait_seconds, "invoice")
    name = inv.get("number") or str(invoice_id)
    chosen = lang_of(inv, lang)
    customer = inv.get("customer") or {}
    tg_url = None
    if link_for and customer.get("id") and inv.get("status") == "completed":
        tg_url = await link_for(customer["id"], f"invoice:{invoice_id}", "receipt")
    if kind == "receipt_80mm":
        return name, await run_in_threadpool(_render_receipt, inv, chosen, tg_url)
    return name, await html_to_pdf(invoice_a4_html(inv, chosen, tg_url))
