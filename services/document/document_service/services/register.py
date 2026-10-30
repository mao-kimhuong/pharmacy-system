"""Controlled-drug register PDF (A4 landscape, Khmer and English headings).

The register lives in the controlled service; this reads it over /internal/v1
(no copy here). Needs controlled.view and the branch. Shows per medicine the
running entries: date, type, lot, in/out, balance, Rx / patient (ID document),
pharmacist, witness, reason – and whether the hash chain verified.
"""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.internal import InternalClient

from .pdf import FONTS, e, html_to_pdf

TYPES = {
    "opening": "Opening · សមតុល្យដើម", "receive": "Received · ទទួល", "dispense": "Dispensed · ចែកចាយ",
    "sale_cancel": "Sale cancelled", "customer_return": "Returned by patient", "supplier_return": "To supplier",
    "transfer_in": "Transfer in", "transfer_out": "Transfer out", "adjust": "Adjustment · កែតម្រូវ",
    "destroy": "Destroyed · បំផ្លាញ", "loss": "Lost", "expired": "Expired", "count_adjust": "Stock take",
    "correction": "Correction · ការកែ",
}  # fmt: skip


def _when(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(clock.TIMEZONE).strftime("%Y-%m-%d %H:%M")


def register_html(data: dict[str, Any], date_from: date | None, date_to: date | None) -> str:
    medicines = {m["id"]: m for m in data["medicines"]}
    sections = []
    for medicine_id, med in medicines.items():
        rows = [x for x in data["entries"] if x["medicine_id"] == medicine_id]
        chain = next((c for c in data["chains"] if c["medicine_id"] == medicine_id), {"valid": True})
        body = "".join(
            f"<tr><td>{e(_when(x['occurred_at']))}</td><td>{e(TYPES.get(x['entry_type'], x['entry_type']))}</td>"
            f"<td>{e(x['lot_no'])}</td><td class='r'>{x['qty_base'] if x['qty_base'] > 0 else ''}</td>"
            f"<td class='r'>{-x['qty_base'] if x['qty_base'] < 0 else ''}</td><td class='r'><b>{x['balance_after']}</b></td>"
            f"<td>{e(x['prescription_number'])}<div>{e(x['patient_name'])} {e(x['patient_id_document'])}</div></td>"
            f"<td>{e(x['actor_name'])}</td><td>{e(x['witness_name'])}</td><td>{e(x['reason'])}</td></tr>"
            for x in rows
        )
        ok = "Chain verified · ត្រឹមត្រូវ" if chain["valid"] else f"CHAIN BROKEN: {e(chain.get('problem'))}"
        sections.append(f"""<h2>{e(med["name"])} {e(med["strength"])} <span class="km" lang="km">{e(med["name_km"])}</span>
          <span class="sub">schedule {e(med["schedule"])} · unit {e(med["base_unit"])} · {ok}</span></h2>
          <table><thead><tr><th>Date · កាលបរិច្ឆេទ</th><th>Entry</th><th>Lot</th><th class="r">In</th>
          <th class="r">Out</th><th class="r">Balance</th><th>Rx / patient · អ្នកជំងឺ</th><th>Pharmacist</th>
          <th>Witness · សាក្សី</th><th>Reason</th></tr></thead><tbody>{body}</tbody></table>""")
    period = f"{date_from or '…'} – {date_to or '…'}"
    css = f"""
      @page {{ size: A4 landscape; margin: 10mm }} * {{ box-sizing: border-box }}
      body {{ font-family: {FONTS}; font-size: 7.5pt; color: #111 }}
      h1 {{ font-size: 13pt; margin: 0 }} h2 {{ font-size: 10pt; margin: 5mm 0 1mm }}
      .sub {{ font-size: 7pt; color: #555; font-weight: 400 }} .km {{ font-weight: 400 }}
      table {{ width: 100%; border-collapse: collapse }} th {{ text-align: left; border-bottom: 0.3mm solid #000 }}
      td, th {{ padding: 0.8mm 1mm; vertical-align: top }} td {{ border-bottom: 0.1mm solid #ccc }}
      .r {{ text-align: right }}
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head><body>
      <h1>Controlled drug register · បញ្ជីថ្នាំគ្រប់គ្រង</h1>
      <div class="sub">{e(data["branch_name_en"])} · <span lang="km">{e(data["branch_name_km"])}</span> · {e(period)}
        · printed {e(clock.now().astimezone(clock.TIMEZONE).strftime("%Y-%m-%d %H:%M"))}</div>
      {"".join(sections) or "<p>No entries.</p>"}
    </body></html>"""


async def render(controlled: InternalClient, actor: CurrentUser, branch_id: UUID, medicine_id: UUID | None,
                 date_from: date | None, date_to: date | None) -> bytes:  # fmt: skip
    actor.require_branch(branch_id)
    data = await controlled.post("/register", {
        "branch_id": str(branch_id), "medicine_id": str(medicine_id) if medicine_id else None,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None}, actor=actor, branch_id=branch_id)  # fmt: skip
    return await html_to_pdf(register_html(data, date_from, date_to))
