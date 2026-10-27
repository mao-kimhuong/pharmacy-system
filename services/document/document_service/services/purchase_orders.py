"""Purchase order PDF (A4), printed from the local copy kept from
purchase_order.* events. Rules:

- Needs purchasing.order and access to the PO's branch (others: 404).
- Right after a PO is created its event may still be on its way: wait up to
  `document_wait_seconds` (5) for it, then DOCUMENT_NOT_READY (409, try again).
- Draft and cancelled POs are printed with a watermark.
"""

import asyncio
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import PurchaseOrderCopy
from .pdf import FONTS, e, html_to_pdf

PO_EVENTS = frozenset({
    "purchase_order.created", "purchase_order.updated", "purchase_order.sent",
    "purchase_order.received", "purchase_order.cancelled",
})  # fmt: skip


async def upsert_po(session: AsyncSession, payload: dict[str, Any]) -> bool:
    po_id = UUID(str(payload["purchase_order_id"]))
    version = int(payload["version"])
    stored = (
        await session.execute(
            select(PurchaseOrderCopy.version).where(PurchaseOrderCopy.id == po_id).with_for_update()
        )
    ).scalar_one_or_none()
    if stored is not None and stored >= version:
        return False
    values = {
        "id": po_id, "version": version, "branch_id": UUID(str(payload["branch"]["id"])),
        "number": str(payload["number"]), "status": str(payload["status"]), "data": payload,
    }  # fmt: skip
    await session.execute(
        insert(PurchaseOrderCopy)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[PurchaseOrderCopy.id], set_={k: v for k, v in values.items() if k != "id"}
        )
    )
    return True


async def wait_for_po(
    session: AsyncSession, actor: CurrentUser, po_id: UUID, wait_seconds: float
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        row = (
            await session.execute(
                select(PurchaseOrderCopy.branch_id, PurchaseOrderCopy.data).where(
                    PurchaseOrderCopy.id == po_id
                )
            )
        ).first()
        await session.rollback()  # end the read, so the next look sees newly committed copies
        if row is not None:
            if not actor.can_access_branch(row.branch_id):
                raise AppError(ErrorCode.NOT_FOUND, "Purchase order not found", status_code=404)
            return row.data
        if asyncio.get_running_loop().time() >= deadline:
            raise AppError(
                ErrorCode.DOCUMENT_NOT_READY,
                "This purchase order has not reached the document service yet; try again in a moment",
                status_code=409,
            )
        await asyncio.sleep(0.25)


def _money(value: str | Decimal) -> str:
    return f"{Decimal(str(value)):,.2f}"


def _cost(value: str | Decimal) -> str:
    d = Decimal(str(value))
    return f"{d:,.2f}" if d == d.quantize(Decimal("0.01")) else f"{d.normalize():,f}"


def build_html(po: dict[str, Any]) -> str:
    branch, supplier = po["branch"], po["supplier"]
    rows = "".join(
        f"<tr><td class='n'>{line['line_no']}</td>"
        f"<td><div class='name'>{e(line['name'])}</div>"
        f"<div class='km' lang='km'>{e(line['name_km'])}</div>"
        f"<div class='sub'>{e(line['sku'])} · {e(' '.join(x for x in (line['strength'], line['dosage_form']) if x))}"
        f"</div></td>"
        f"<td>{e(line['pack_unit'])}<div class='sub'>{line['qty_in_base']} {e(line['base_unit'])}</div></td>"
        f"<td class='r'>{line['qty']:,}</td><td class='r'>{_cost(line['unit_cost'])}</td>"
        f"<td class='r'>{_money(line['line_total'])}</td></tr>"
        for line in po["lines"]
    )
    status = po["status"]
    watermark = (
        f"<div class='watermark'>{e(status.upper())}</div>" if status in ("draft", "cancelled") else ""
    )
    cancel = f"<p class='cancel'>Cancelled: {e(po.get('cancel_reason'))}</p>" if status == "cancelled" else ""
    dates = (po.get("sent_at") or po.get("created_at") or "")[:10]
    expected = f"<div>Expected: {e(po['expected_on'])}</div>" if po.get("expected_on") else ""
    note = f"<p class='note'>{e(po['note'])}</p>" if po.get("note") else ""
    css = f"""
      @page {{ size: A4; margin: 14mm 12mm 16mm;
               @bottom-right {{ content: "Page " counter(page) " / " counter(pages); font-size: 8pt;
                               font-family: {FONTS} }} }}
      * {{ box-sizing: border-box }} body {{ font-family: {FONTS}; font-size: 9.5pt; color: #111 }}
      h1 {{ font-size: 16pt; margin: 0 }} .km {{ font-size: 9pt }}
      .head {{ display: flex; justify-content: space-between; border-bottom: 0.4mm solid #000; padding-bottom: 3mm }}
      .head .right {{ text-align: right }} .number {{ font-size: 12pt; font-weight: 700 }}
      .parties {{ display: flex; gap: 8mm; margin: 4mm 0 }} .parties > div {{ flex: 1 }}
      .label {{ font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.4pt; color: #555 }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 3mm }}
      th {{ text-align: left; font-size: 8pt; border-bottom: 0.3mm solid #000; padding: 1.5mm 1mm }}
      td {{ border-bottom: 0.2mm solid #ccc; padding: 1.5mm 1mm; vertical-align: top }}
      tr {{ break-inside: avoid }} .r {{ text-align: right; white-space: nowrap }} .n {{ width: 6mm }}
      .name {{ font-weight: 700 }} .sub {{ font-size: 7.5pt; color: #555 }}
      .total td {{ border: 0; font-weight: 700; font-size: 11pt; padding-top: 3mm }}
      .watermark {{ position: fixed; top: 110mm; left: 0; right: 0; text-align: center; font-size: 72pt;
                    color: rgba(0,0,0,0.08); transform: rotate(-25deg); font-weight: 700 }}
      .cancel {{ color: #a00; font-weight: 700 }} .note {{ margin-top: 4mm }}
      .sign {{ display: flex; gap: 20mm; margin-top: 18mm }}
      .sign div {{ flex: 1; border-top: 0.2mm solid #000; padding-top: 1mm; font-size: 8pt }}
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head><body>
      {watermark}
      <div class="head">
        <div><h1>{e(branch["name_en"])}</h1><div class="km" lang="km">{e(branch["name_km"])}</div>
             <div class="sub">Branch {e(branch["code"])}</div></div>
        <div class="right"><div class="label">Purchase order · ប័ណ្ណបញ្ជាទិញ</div>
             <div class="number">{e(po["number"])}</div><div>Date: {e(dates)}</div>{expected}
             <div>Status: {e(status.replace("_", " "))}</div></div>
      </div>
      <div class="parties">
        <div><div class="label">Supplier · អ្នកផ្គត់ផ្គង់</div><b>{e(supplier["name"])}</b>
             <div class="km" lang="km">{e(supplier.get("name_km"))}</div>
             <div>{e(supplier.get("address"))}</div><div>{e(supplier.get("phone"))}</div>
             <div class="sub">Code {e(supplier["code"])} · terms {supplier.get("payment_terms_days", 0)} days</div></div>
        <div><div class="label">Deliver to · ដឹកជញ្ជូនទៅ</div><b>{e(branch["name_en"])}</b>
             <div class="km" lang="km">{e(branch["name_km"])}</div></div>
      </div>
      {cancel}
      <table><thead><tr><th>#</th><th>Item</th><th>Pack</th><th class="r">Qty</th>
        <th class="r">Unit cost (USD)</th><th class="r">Amount (USD)</th></tr></thead>
        <tbody>{rows}</tbody>
        <tfoot><tr class="total"><td colspan="5" class="r">Total USD</td>
          <td class="r">{_money(po["total"])}</td></tr></tfoot></table>
      {note}
      <div class="sign"><div>Ordered by</div><div>Approved by</div><div>Supplier</div></div>
    </body></html>"""


async def render_po(
    session: AsyncSession, actor: CurrentUser, po_id: UUID, wait_seconds: float
) -> tuple[str, bytes]:
    po = await wait_for_po(session, actor, po_id, wait_seconds)
    return po["number"], await html_to_pdf(build_html(po))
