"""Dispensing labels and the patient's Rx summary (S4). Rules:

Dispensing label (`type: dispensing_label`, pos.dispense_rx or prescriptions.view,
own branches): one label per Rx line of a completed invoice (or just `line_no`),
from the copy of invoice.* events: patient, medicine, quantity, directions
(dosage, frequency, duration), Rx number, doctor, date, lot + expiry, the
dispensing pharmacist, the branch. Khmer (`lang: km`, default) or English.
Size from the branch setting `dispensing_label_size` (70x40 default, 50x30,
100x50: one label per page for label printers; a4_sheet: 70×40 labels on A4),
carried in the invoice snapshot; `size` in the request overrides it.

Rx summary (`type: rx_summary`, prescriptions.view): the patient (allergies,
conditions) and their prescriptions at the branches the user works in, with
dispensed and remaining quantities. Printing is written to the User Log.
"""

import asyncio
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import InvoiceCopy, OutboxEvent, PatientCopy, PrescriptionCopy, StaffCopy
from .pdf import FONTS, e, html_to_pdf
from .stored import upsert_versioned, wait_for

Size = Literal["70x40", "50x30", "100x50", "a4_sheet"]
Lang = Literal["km", "en"]
PATIENT_EVENTS = frozenset({"patient.created", "patient.updated", "patient.activated", "patient.deactivated"})
RX_EVENTS = frozenset({
    "prescription.created", "prescription.updated", "prescription.activated", "prescription.cancelled",
    "prescription.dispensed", "prescription.expired",
})  # fmt: skip
USER_EVENTS = frozenset({"user.created", "user.updated", "user.activated", "user.deactivated"})
SIZES_MM = {"70x40": (70, 40), "50x30": (50, 30), "100x50": (100, 50), "a4_sheet": (70, 40)}
# The Khmer wording should be checked by a Khmer-speaking pharmacist.
WORDS = {
    "en": {"patient": "Patient", "qty": "Qty", "take": "Take", "for": "for", "days": "days", "rx": "Rx",
           "dr": "Doctor:", "lot": "Lot", "exp": "Exp", "by": "By", "date": "Date"},
    "km": {"patient": "អ្នកជំងឺ", "qty": "ចំនួន", "take": "លេប", "for": "រយៈពេល", "days": "ថ្ងៃ",
           "rx": "វេជ្ជបញ្ជា", "dr": "វេជ្ជបណ្ឌិត", "lot": "ឡូត៍", "exp": "ផុតកំណត់", "by": "ឱសថការី",
           "date": "កាលបរិច្ឆេទ"},
}  # fmt: skip


# ---------------------------------------------------------------- copies


async def upsert_staff(session: AsyncSession, payload: dict[str, Any]) -> None:
    values = {"id": UUID(str(payload["user_id"])), "name": payload.get("name") or "",
              "is_active": bool(payload.get("is_active", True))}  # fmt: skip
    await session.execute(insert(StaffCopy).values(**values).on_conflict_do_update(
        index_elements=[StaffCopy.id], set_={k: v for k, v in values.items() if k != "id"}))  # fmt: skip


async def upsert_patient(session: AsyncSession, payload: dict[str, Any]) -> bool:
    return await upsert_versioned(session, PatientCopy, {
        "id": UUID(str(payload["patient_id"])), "version": int(payload["version"]), "data": payload})  # fmt: skip


async def upsert_prescription(session: AsyncSession, payload: dict[str, Any]) -> bool:
    return await upsert_versioned(session, PrescriptionCopy, {
        "id": UUID(str(payload["prescription_id"])), "version": int(payload["version"]),
        "branch_id": UUID(str(payload["branch_id"])), "patient_id": UUID(str(payload["patient"]["id"])),
        "number": payload["number"], "data": payload})  # fmt: skip


# ---------------------------------------------------------------- dispensing label


def _date(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso).astimezone(clock.TIMEZONE).strftime("%d-%m-%Y")


def _label(inv: dict[str, Any], line: dict[str, Any], lang: Lang, pharmacist: str) -> str:
    w, rx = WORDS[lang], line["rx"]
    patient = (rx["patient_name_km"] or rx["patient_name_en"]) if lang == "km" else (
        rx["patient_name_en"] or rx["patient_name_km"])  # fmt: skip
    medicine = line["name_km"] if lang == "km" and line.get("name_km") else line["name"]
    directions = " · ".join(x for x in (rx.get("dosage"), rx.get("frequency")) if x)
    duration = f"{w['for']} {rx['duration_days']} {w['days']}" if rx.get("duration_days") else ""
    lots = ", ".join(f"{b['lot_no']} ({w['exp']} {b['expiry_date']})" for b in line.get("batches") or [])
    b = inv["branch"]
    return f"""<section class="label" lang="{lang}">
      <div class="top"><b>{e(b["name_km"] if lang == "km" and b.get("name_km") else b["name_en"])}</b>
        <span>{e(_date(inv.get("completed_at")))}</span></div>
      <div class="patient">{w["patient"]}: <b>{e(patient)}</b></div>
      <div class="med">{e(medicine)}</div>
      <div>{w["qty"]}: <b>{line["qty_base"]}</b> · {
        e(line["pack_unit"]) if line["qty_in_base"] == 1 else e(f"{line['qty']} {line['pack_unit']}")
    }</div>
      <div class="dir">{w["take"]}: {e(directions)} {e(duration)}</div>
      <div class="small">{w["rx"]} {e(rx["prescription_number"])} · {w["dr"]} {e(rx.get("doctor_name"))}</div>
      <div class="small">{w["lot"]}: {e(lots)}</div>
      <div class="small">{w["by"]}: {e(pharmacist)} · {e(inv.get("number"))}</div>
    </section>"""


def labels_html(
    inv: dict[str, Any], lines: list[dict[str, Any]], size: Size, lang: Lang, pharmacist: str
) -> str:
    width, height = SIZES_MM[size]
    labels = "".join(_label(inv, x, lang, pharmacist) for x in lines)
    if size == "a4_sheet":
        page = "@page { size: A4; margin: 8mm 0 0 0 } body { display: flex; flex-wrap: wrap }"
        box = f"width: {width}mm; height: {height}mm; padding: 2mm 3mm; border: 0.1mm dashed #bbb"
    else:
        page = f"@page {{ size: {width}mm {height}mm; margin: 0 }}"
        box = f"width: {width}mm; height: {height}mm; padding: 1.5mm 2.5mm; page-break-after: always"
    font = 6.2 if size == "50x30" else 8.5 if size == "100x50" else 7
    css = f"""{page}
      * {{ box-sizing: border-box; margin: 0 }}
      body {{ font-family: {FONTS}; font-size: {font}pt; line-height: 1.25; color: #000 }}
      .label {{ {box}; overflow: hidden }} .label:last-child {{ page-break-after: auto }}
      .top {{ display: flex; justify-content: space-between; border-bottom: 0.2mm solid #000; margin-bottom: 0.6mm }}
      .med {{ font-weight: 700; font-size: {font + 1.5}pt }} .dir {{ font-weight: 700 }}
      .small {{ font-size: {font - 1}pt }}
    """
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>
      <body>{labels}</body></html>"""


async def render_label(
    session: AsyncSession, actor: CurrentUser, invoice_id: UUID, line_no: int | None, size: Size | None,
    lang: Lang, wait_seconds: float,
) -> tuple[str, bytes]:  # fmt: skip
    inv = await wait_for(session, InvoiceCopy, invoice_id, actor, wait_seconds, "invoice")
    lines = [x for x in inv["lines"] if x.get("rx") and (line_no is None or x["line_no"] == line_no)]
    if not lines:
        raise AppError(ErrorCode.NOT_FOUND, "No prescription line to label on this invoice", status_code=404)
    if inv["status"] != "completed":
        raise AppError(ErrorCode.INVOICE_STATE, f"The invoice is {inv['status']}: no label", status_code=409)
    staff = await session.get(StaffCopy, UUID(inv["cashier_id"]))
    size = size or inv["branch"].get("dispensing_label_size") or "70x40"
    pdf = await html_to_pdf(labels_html(inv, lines, size, lang, staff.name if staff else ""))
    return inv.get("number") or str(invoice_id), pdf


# ---------------------------------------------------------------- Rx summary


def _summary_row(i: dict[str, Any]) -> str:
    days = f" · {i['duration_days']} days" if i.get("duration_days") else ""
    return (
        f"<tr><td>{i['line_no']}</td><td><b>{e(i['name'])}</b> {e(i['strength'])}"
        f"<div class='km' lang='km'>{e(i['name_km'])}</div></td>"
        f"<td>{e(i['dosage'])} {e(i['frequency'])}{e(days)}</td>"
        f"<td class='r'>{i['qty_base']} × {1 + i['repeats_allowed']}</td>"
        f"<td class='r'>{i['dispensed_base']}</td><td class='r'>{i['remaining_base']}</td></tr>"
    )


def summary_html(patient: dict[str, Any], rxs: list[dict[str, Any]]) -> str:
    allergies = (
        ", ".join(f"{a['value']} ({a['kind']})" for a in patient.get("allergies") or []) or "None recorded"
    )
    blocks = []
    for rx in rxs:
        rows = "".join(_summary_row(i) for i in rx["items"])
        blocks.append(f"""<h2>{e(rx["number"])} <span class="st">{
            e(rx["status"].replace("_", " "))
        }</span></h2>
          <div class="sub">Issued {e(rx["issued_on"])} · valid until {e(rx["valid_until"])} · Doctor: {
            e(rx["doctor"]["name"])
        } ({e(rx["doctor"]["licence_no"])}) {e(rx["doctor"].get("clinic"))}
            {f" · paper Rx {e(rx['rx_no'])}" if rx.get("rx_no") else ""}</div>
          <table><thead><tr><th>#</th><th>Medicine</th><th>Directions</th><th class="r">Qty × fills</th>
          <th class="r">Dispensed</th><th class="r">Remaining</th></tr></thead><tbody>{
            rows
        }</tbody></table>""")
    css = f"""
      @page {{ size: A4; margin: 14mm 12mm }} * {{ box-sizing: border-box }}
      body {{ font-family: {FONTS}; font-size: 9.5pt; color: #111 }}
      h1 {{ font-size: 15pt; margin: 0 }} h2 {{ font-size: 11pt; margin: 6mm 0 1mm }}
      .km {{ font-size: 9pt }} .sub {{ font-size: 8pt; color: #555 }} .st {{ font-size: 8pt; font-weight: 400 }}
      .alert {{ border: 0.4mm solid #000; padding: 2mm; margin-top: 3mm }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 2mm }}
      th {{ text-align: left; font-size: 8pt; border-bottom: 0.3mm solid #000; padding: 1.2mm 1mm }}
      td {{ border-bottom: 0.2mm solid #ccc; padding: 1.2mm 1mm; vertical-align: top }} .r {{ text-align: right }}
    """
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{css}</style></head><body>
      <div class="sub">PRESCRIPTION SUMMARY · សេចក្ដីសង្ខេបវេជ្ជបញ្ជា · printed {
        e(clock.now().astimezone(clock.TIMEZONE).strftime("%Y-%m-%d %H:%M"))
    }</div>
      <h1>{e(patient.get("name_en"))}</h1><div class="km" lang="km">{e(patient.get("name_km"))}</div>
      <div class="sub">{e(patient.get("sex"))} · born {e(patient.get("dob") or "–")} · {
        e(patient.get("phone"))
    }</div>
      <div class="alert"><b>Allergies · អាឡែហ្ស៊ី:</b> {e(allergies)}<br>
        <b>Conditions:</b> {e(patient.get("chronic_conditions") or "–")}</div>
      {"".join(blocks) or "<p>No prescriptions.</p>"}
    </body></html>"""


async def render_summary(
    session: AsyncSession, actor: CurrentUser, patient_id: UUID, wait_seconds: float
) -> tuple[str, bytes]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while (row := await session.get(PatientCopy, patient_id, populate_existing=True)) is None:
        await session.rollback()
        if loop.time() >= deadline:
            raise AppError(ErrorCode.DOCUMENT_NOT_READY, "This patient has not reached the document service yet",
                           status_code=409)  # fmt: skip
        await asyncio.sleep(0.25)
    patient = row.data
    branches = {UUID(b) for b in patient.get("branch_ids") or []}
    if not (actor.is_owner or branches & set(actor.branch_ids)):
        raise AppError(ErrorCode.NOT_FOUND, "Patient not found", status_code=404)
    query = select(PrescriptionCopy.data).where(PrescriptionCopy.patient_id == patient_id)
    if not actor.is_owner:
        query = query.where(PrescriptionCopy.branch_id.in_(list(actor.branch_ids)))
    rxs = [r for r in (await session.execute(query)).scalars() if r["status"] != "draft"]
    rxs.sort(key=lambda r: (r["issued_on"], r["number"]), reverse=True)
    record_audit(session, OutboxEvent, service="document", action="rx_summary.printed", entity_type="patient",
                 entity_id=patient_id, actor=actor, branch_id=None, after={"prescriptions": len(rxs)})  # fmt: skip
    await session.commit()
    return "rx-summary", await html_to_pdf(summary_html(patient, rxs))
