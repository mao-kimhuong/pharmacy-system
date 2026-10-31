"""Quote / sale order (A4, Khmer/English) from the copy of sale_order.* events:
customer, lines with promotions, total, the deposit taken, valid / reserved
until. Permission sales.orders or sales.view at the order's branch."""

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import SaleOrderCopy
from .pdf import FONTS, e, html_to_pdf
from .stored import upsert_versioned
from .transfer_note import _when

ORDER_EVENTS = frozenset({"sale_order.created", "sale_order.ordered", "sale_order.invoiced", "sale_order.updated",
                          "sale_order.cancelled", "sale_order.closed"})  # fmt: skip


async def upsert_order(session: AsyncSession, p: dict[str, Any]) -> bool:
    return await upsert_versioned(session, SaleOrderCopy, {
        "id": UUID(p["sale_order_id"]), "version": int(p["version"]), "branch_id": UUID(p["branch"]["id"]),
        "number": p["number"], "data": p})  # fmt: skip


def order_html(o: dict[str, Any]) -> str:
    quote = o["status"] == "quote"
    title = "QUOTATION · សម្រង់តម្លៃ" if quote else "SALE ORDER · បញ្ជាលក់"
    rows = "".join(
        f"<tr><td>{x['line_no']}</td><td><b>{e(x['name'])}</b>"
        f"<div class='km' lang='km'>{e(x.get('name_km') or '')}</div><div class='sub'>{e(x['sku'])}</div></td>"
        f"<td class='r'>{x['qty']} {e(x['pack_unit'])}</td><td class='r'>{e(x['unit_price'])}</td>"
        f"<td class='r'>{'-' + e(x['promo_discount']) if x['promo_discount'] not in ('0', '0.00') else ''}</td>"
        f"<td class='r'>{e(x['line_total'])}</td></tr>"
        for x in o["lines"]
    )  # fmt: skip
    b, c = o["branch"], o["customer"]
    css = f"""
      @page {{ size: A4; margin: 14mm 12mm }} * {{ box-sizing: border-box }}
      body {{ font-family: {FONTS}; font-size: 9.5pt; color: #111 }} h1 {{ font-size: 15pt; margin: 0 }}
      .head {{ display: flex; justify-content: space-between; border-bottom: 0.4mm solid #000; padding-bottom: 3mm }}
      .km {{ font-size: 9pt }} .sub {{ font-size: 7.5pt; color: #555 }} .label {{ font-size: 7.5pt; color: #555 }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 4mm }}
      th {{ text-align: left; font-size: 8pt; border-bottom: 0.3mm solid #000; padding: 1.2mm 1mm }}
      td {{ border-bottom: 0.2mm solid #ccc; padding: 1.5mm 1mm; vertical-align: top }} .r {{ text-align: right }}
      .totals {{ margin-left: auto; width: 70mm; margin-top: 3mm }} .totals div {{ display: flex;
        justify-content: space-between; padding: 0.8mm 0 }} .big {{ font-weight: bold; font-size: 11pt }}
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head><body>
      <div class="head">
        <div><div class="label">{title}</div><h1>{e(o["number"])}</h1>
          <div>Status: {e(o["status"])} · {e(_when(o.get("created_at")))}</div>
          {f"<div>Valid until · មានសុពលភាពដល់ {e(o['valid_until'])}</div>" if quote and o.get("valid_until") else ""}
          {f"<div>Reserved until · កក់ទុកដល់ {e(_when(o['reserve_until']))}</div>" if o.get("reserve_until") else ""}
          {f"<div>Cancelled: {e(o['cancel_reason'])}</div>" if o.get("cancel_reason") else ""}</div>
        <div style="text-align:right"><b>{e(b["name_en"])}</b> ({e(b["code"])})
          <div class="km" lang="km">{e(b["name_km"])}</div></div>
      </div>
      <p><span class="label">Customer · អតិថិជន</span><br><b>{e(c["name"])}</b>
        <span class="km" lang="km">{e(c.get("name_km") or "")}</span> {e(c.get("phone") or "")}</p>
      <table><thead><tr><th>#</th><th>Medicine · ឱសថ</th><th class="r">Qty · ចំនួន</th><th class="r">Price</th>
        <th class="r">Promotion</th><th class="r">Amount · ទឹកប្រាក់</th></tr></thead><tbody>{rows}</tbody></table>
      <div class="totals">
        <div><span>Subtotal</span><span>{e(o["subtotal"])}</span></div>
        <div><span>Discount</span><span>-{e(o["discount"])}</span></div>
        <div class="big"><span>Total USD · សរុប</span><span>{e(o["total"])}</span></div>
        <div><span>Deposit · ប្រាក់កក់</span><span>{e(o["deposit_usd"])}</span></div>
      </div>
      {f"<p>Note: {e(o['note'])}</p>" if o.get("note") else ""}
    </body></html>"""


async def render(
    session: AsyncSession, actor: CurrentUser, order_id: UUID, wait_seconds: float
) -> tuple[str, bytes]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while (row := await session.get(SaleOrderCopy, order_id, populate_existing=True)) is None:
        await session.rollback()
        if loop.time() >= deadline:
            raise AppError(ErrorCode.DOCUMENT_NOT_READY, "This order has not reached the document service yet",
                           status_code=409)  # fmt: skip
        await asyncio.sleep(0.25)
    if not actor.can_access_branch(row.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Sale order not found", status_code=404)
    return row.number, await html_to_pdf(order_html(row.data))
