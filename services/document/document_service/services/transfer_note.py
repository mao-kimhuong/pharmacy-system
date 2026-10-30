"""Transfer note (A4, Khmer/English) from the copy of transfer.* events: the
batches (lot, expiry, quantity – no cost), both branches, who sent and who
received, and a QR code of the transfer number: the receiving branch scans it to
open the transfer (GET /api/inventory/v1/transfers/by-number/{number}).
Permission: any transfers.* permission at the source or the destination."""

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

import segno
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import TransferCopy
from .pdf import FONTS, e, html_to_pdf
from .stored import upsert_versioned

TRANSFER_EVENTS = frozenset({"transfer.created", "transfer.picked", "transfer.dispatched", "transfer.received",
                             "transfer.closed", "transfer.cancelled", "transfer.updated"})  # fmt: skip
PERMISSIONS = (
    "transfers.request",
    "transfers.approve",
    "transfers.dispatch",
    "transfers.receive",
    "transfers.resolve",
)


async def upsert_transfer(session: AsyncSession, p: dict[str, Any]) -> bool:
    return await upsert_versioned(session, TransferCopy, {
        "id": UUID(p["transfer_id"]), "version": int(p["version"]), "from_branch_id": UUID(p["from_branch"]["id"]),
        "to_branch_id": UUID(p["to_branch"]["id"]), "number": p["number"], "data": p})  # fmt: skip


def qr_data_uri(text: str) -> str:
    return segno.make(text, error="m").svg_data_uri(scale=4, border=1)


def _when(value: str | None) -> str:
    return (
        datetime.fromisoformat(value).astimezone(clock.TIMEZONE).strftime("%Y-%m-%d %H:%M") if value else ""
    )


def note_html(t: dict[str, Any]) -> str:
    lines = {x["line_no"]: x for x in t["lines"]}
    picks = t.get("picks") or []
    rows = "".join(
        f"<tr><td>{p['line_no']}</td><td><b>{e(lines[p['line_no']]['name'])}</b>"
        f"<div class='km' lang='km'>{e(lines[p['line_no']]['name_km'])}</div>"
        f"<div class='sub'>{e(lines[p['line_no']]['sku'])}{' · controlled' if lines[p['line_no']]['is_controlled'] else ''}"
        f"</div></td><td>{e(p['lot_no'])}</td><td>{e(p['expiry_date'])}</td>"
        f"<td class='r'>{p['qty_base']:,} {e(lines[p['line_no']]['base_unit'])}</td>"
        f"<td class='r'>{'' if p['qty_received'] is None else p['qty_received']}</td><td></td></tr>"
        for p in picks
    ) or "".join(
        f"<tr><td>{x['line_no']}</td><td><b>{e(x['name'])}</b></td><td colspan='2' class='sub'>not picked yet</td>"
        f"<td class='r'>{x['qty_base']:,} {e(x['base_unit'])}</td><td></td><td></td></tr>" for x in t["lines"]
    )  # fmt: skip
    f, to = t["from_branch"], t["to_branch"]
    css = f"""
      @page {{ size: A4; margin: 14mm 12mm }} * {{ box-sizing: border-box }}
      body {{ font-family: {FONTS}; font-size: 9.5pt; color: #111 }} h1 {{ font-size: 15pt; margin: 0 }}
      .head {{ display: flex; justify-content: space-between; border-bottom: 0.4mm solid #000; padding-bottom: 3mm }}
      .km {{ font-size: 9pt }} .sub {{ font-size: 7.5pt; color: #555 }} .label {{ font-size: 7.5pt; color: #555 }}
      .parties {{ display: flex; gap: 8mm; margin: 4mm 0 }} .parties > div {{ flex: 1 }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 2mm }}
      th {{ text-align: left; font-size: 8pt; border-bottom: 0.3mm solid #000; padding: 1.2mm 1mm }}
      td {{ border-bottom: 0.2mm solid #ccc; padding: 1.5mm 1mm; vertical-align: top }} .r {{ text-align: right }}
      .sign {{ display: flex; gap: 12mm; margin-top: 16mm }}
      .sign div {{ flex: 1; border-top: 0.2mm solid #000; padding-top: 1mm; font-size: 8pt }}
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head><body>
      <div class="head">
        <div><div class="label">TRANSFER NOTE · ប័ណ្ណផ្ទេរស្តុក</div><h1>{e(t["number"])}</h1>
          <div>Status: {e(t["status"])} · created {e(_when(t.get("created_at")))}</div>
          {f"<div>Request {e(t['request_number'])}</div>" if t.get("request_number") else ""}</div>
        <div><img src="{qr_data_uri(t["number"])}" style="width:28mm;height:28mm" alt="{e(t["number"])}"></div>
      </div>
      <div class="parties">
        <div><div class="label">From · ពី</div><b>{e(f["name_en"])}</b> ({e(f["code"])})
          <div class="km" lang="km">{e(f["name_km"])}</div>
          <div class="sub">{f"Sent {e(_when(t['dispatched_at']))}" if t.get("dispatched_at") else "Not sent yet"}
            {f"· witness {e(t['dispatch_witness'])}" if t.get("dispatch_witness") else ""}</div></div>
        <div><div class="label">To · ទៅ</div><b>{e(to["name_en"])}</b> ({e(to["code"])})
          <div class="km" lang="km">{e(to["name_km"])}</div>
          <div class="sub">{f"Received {e(_when(t['received_at']))}" if t.get("received_at") else "Not received yet"}
            {f"· witness {e(t['receive_witness'])}" if t.get("receive_witness") else ""}</div></div>
      </div>
      <table><thead><tr><th>#</th><th>Medicine · ឱសថ</th><th>Lot</th><th>Expiry · ផុតកំណត់</th><th class="r">Sent</th>
        <th class="r">Received</th><th>Remark</th></tr></thead><tbody>{rows}</tbody></table>
      {f"<p>Note: {e(t['note'])}</p>" if t.get("note") else ""}
      <div class="sign"><div>Picked by · អ្នករៀបចំ</div><div>Sent by · អ្នកផ្ញើ</div><div>Received by · អ្នកទទួល</div></div>
    </body></html>"""


async def render(
    session: AsyncSession, actor: CurrentUser, transfer_id: UUID, wait_seconds: float
) -> tuple[str, bytes]:
    if not actor.has_any(*PERMISSIONS):
        actor.require("transfers.receive")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while (row := await session.get(TransferCopy, transfer_id, populate_existing=True)) is None:
        await session.rollback()
        if loop.time() >= deadline:
            raise AppError(ErrorCode.DOCUMENT_NOT_READY, "This transfer has not reached the document service yet",
                           status_code=409)  # fmt: skip
        await asyncio.sleep(0.25)
    if not (actor.can_access_branch(row.from_branch_id) or actor.can_access_branch(row.to_branch_id)):
        raise AppError(ErrorCode.NOT_FOUND, "Transfer not found", status_code=404)
    return row.number, await html_to_pdf(note_html(row.data))
