"""Two A4 documents (S8b), Khmer or English:

- supplier_return: the return note for the supplier, from the copy of
  supplier_return.* events (purchasing.return, own branches; values only for users
  who may see purchase prices).
- customer_statement: a customer's statement (contacts.customers), read from the
  customers service (/internal/v1/customers/{id}/statement).
"""

import asyncio
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient

from ..models import SupplierReturnCopy
from .pdf import FONTS, e, html_to_pdf
from .stored import upsert_versioned

RETURN_EVENTS = frozenset({"supplier_return.created", "supplier_return.submitted", "supplier_return.cancelled"})
PRICES = ("purchasing.order", "purchasing.pay", "finance.cost_profit")
T = {
    "en": {"return": "RETURN TO SUPPLIER", "statement": "CUSTOMER STATEMENT", "supplier": "Supplier",
           "reason": "Reason", "lot": "Lot", "expiry": "Expiry", "qty": "Qty (base)", "cost": "Cost / base",
           "value": "Value (USD)", "total": "Total USD", "sign": ("Prepared by", "Supplier received"),
           "date": "Date", "doc": "Document", "debit": "Debit", "credit": "Credit", "balance": "Balance",
           "opening": "Opening balance", "closing": "Closing balance", "medicine": "Medicine"},
    "km": {"return": "ប្រគល់ទំនិញត្រឡប់ទៅអ្នកផ្គត់ផ្គង់", "statement": "របាយការណ៍គណនីអតិថិជន", "supplier": "អ្នកផ្គត់ផ្គង់",
           "reason": "មូលហេតុ", "lot": "ឡូត", "expiry": "ផុតកំណត់", "qty": "ចំនួន", "cost": "ថ្លៃដើម/ឯកតា",
           "value": "តម្លៃ (USD)", "total": "សរុប (USD)", "sign": ("អ្នករៀបចំ", "អ្នកផ្គត់ផ្គង់ទទួល"),
           "date": "កាលបរិច្ឆេទ", "doc": "ឯកសារ", "debit": "ជំពាក់", "credit": "បានបង់", "balance": "សមតុល្យ",
           "opening": "សមតុល្យដើមគ្រា", "closing": "សមតុល្យចុងគ្រា", "medicine": "ឱសថ"},
}  # fmt: skip
CSS = f"""
  @page {{ size: A4; margin: 14mm 12mm }} * {{ box-sizing: border-box }}
  body {{ font-family: {FONTS}; font-size: 9.5pt; color: #111 }} h1 {{ font-size: 14pt; margin: 0 }}
  .sub {{ font-size: 8pt; color: #555 }} table {{ width: 100%; border-collapse: collapse; margin-top: 4mm }}
  th {{ text-align: left; font-size: 8pt; border-bottom: 0.3mm solid #000; padding: 1.2mm 1mm }}
  td {{ border-bottom: 0.2mm solid #ccc; padding: 1.4mm 1mm; vertical-align: top }} .r {{ text-align: right }}
  .head {{ display: flex; justify-content: space-between; border-bottom: 0.4mm solid #000; padding-bottom: 3mm }}
  .sign {{ display: flex; gap: 14mm; margin-top: 18mm }} .sign div {{ flex: 1; border-top: 0.2mm solid #000;
  padding-top: 1mm; font-size: 8pt }}
"""


async def upsert_return(session: AsyncSession, p: dict[str, Any]) -> bool:
    return await upsert_versioned(session, SupplierReturnCopy, {
        "id": UUID(p["return_id"]), "version": int(p["version"]), "branch_id": UUID(p["branch"]["id"]),
        "number": p["number"], "data": p})  # fmt: skip


def return_html(r: dict[str, Any], lang: str, prices: bool) -> str:
    t = T[lang]
    head = (f"<th>#</th><th>{t['medicine']}</th><th>{t['lot']}</th><th>{t['expiry']}</th><th class='r'>{t['qty']}</th>"
            + (f"<th class='r'>{t['cost']}</th><th class='r'>{t['value']}</th>" if prices else ""))  # fmt: skip
    rows = "".join(
        f"<tr><td>{x['line_no']}</td><td><b>{e(x['name'])}</b><div class='sub'>{e(x['sku'])}</div></td>"
        f"<td>{e(x['lot_no'])}</td><td>{e(x.get('expiry_date') or '')}</td><td class='r'>{x['qty_base']:,}</td>"
        + (f"<td class='r'>{e(x.get('cost_per_base') or '')}</td><td class='r'>{e(x['line_total'])}</td>" if prices else "")
        + "</tr>" for x in r["lines"]
    )  # fmt: skip
    total = f"<p style='text-align:right'><b>{t['total']}: {e(r['total'])}</b></p>" if prices else ""
    b, s = r["branch"], r["supplier"]
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
      <div class="head"><div><div class="sub">{t["return"]}</div><h1>{e(r["number"])}</h1>
        <div>{e(r["status"])} · {e((r.get("submitted_at") or "")[:10])}</div></div>
        <div style="text-align:right"><b>{e(b["name_en"])}</b> ({e(b["code"])})<div lang="km">{e(b["name_km"])}</div></div></div>
      <p>{t["supplier"]}: <b>{e(s["name"])}</b> ({e(s["code"])}) · {t["reason"]}: {e(r["reason"])}</p>
      {f"<p class='sub'>{e(r['note'])}</p>" if r.get("note") else ""}
      <table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>{total}
      <div class="sign"><div>{t["sign"][0]}</div><div>{t["sign"][1]}</div></div>
    </body></html>"""


async def render_return(session: AsyncSession, actor: CurrentUser, return_id: UUID, lang: str,
                        wait_seconds: float) -> tuple[str, bytes]:  # fmt: skip
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while (row := await session.get(SupplierReturnCopy, return_id, populate_existing=True)) is None:
        await session.rollback()
        if loop.time() >= deadline:
            raise AppError(ErrorCode.DOCUMENT_NOT_READY, "This return has not reached the document service yet",
                           status_code=409)  # fmt: skip
        await asyncio.sleep(0.25)
    if not actor.can_access_branch(row.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Supplier return not found", status_code=404)
    prices = actor.is_owner or actor.has_any(*PRICES)
    return row.number, await html_to_pdf(return_html(row.data, lang, prices))


def statement_html(st: dict[str, Any], lang: str) -> str:
    t = T[lang]
    rows = "".join(
        f"<tr><td>{e(x.get('on') or x.get('date') or '')}</td><td>{e(x.get('document_no') or x.get('number') or '')}</td>"
        f"<td>{e(x.get('kind') or '')}</td><td class='r'>{e(x.get('debit') or '')}</td>"
        f"<td class='r'>{e(x.get('credit') or '')}</td><td class='r'>{e(x.get('balance') or '')}</td></tr>"
        for x in st.get("entries") or []
    )  # fmt: skip
    period = f"{st.get('from') or '…'} – {st.get('to') or date.today().isoformat()}"
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><style>{CSS}</style></head><body>
      <div class="head"><div><div class="sub">{t["statement"]}</div><h1>{e(st.get("customer") or "")}</h1>
        <div>{e(period)}</div></div></div>
      <p>{t["opening"]}: <b>{e(st.get("opening_balance"))}</b> USD</p>
      <table><thead><tr><th>{t["date"]}</th><th>{t["doc"]}</th><th></th><th class="r">{t["debit"]}</th>
        <th class="r">{t["credit"]}</th><th class="r">{t["balance"]}</th></tr></thead><tbody>{rows}</tbody></table>
      <p style="text-align:right">{t["closing"]}: <b>{e(st.get("closing_balance"))}</b> USD</p>
    </body></html>"""


async def render_statement(customers: InternalClient, actor: CurrentUser, customer_id: UUID,
                           date_from: date | None, date_to: date | None, lang: str) -> tuple[str, bytes]:  # fmt: skip
    params = {k: v.isoformat() for k, v in (("date_from", date_from), ("date_to", date_to)) if v}
    st = await customers.get(f"/customers/{customer_id}/statement", params, actor=actor)
    return f"statement-{st.get('customer') or customer_id}", await html_to_pdf(statement_html(st, lang))
