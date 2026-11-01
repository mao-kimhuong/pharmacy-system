"""Which sales sold these batches (a recall: who may have the medicine). Completed
or returned invoices of the user's branches; the customer always, the patient
(Rx lines) only for users with prescriptions.view."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import Invoice, InvoiceLine, InvoiceLineBatch, KnownCustomer

MAX_BATCHES = 50


async def invoices_by_batches(session: AsyncSession, actor: CurrentUser, batch_ids: list[UUID]) -> list[dict[str, Any]]:
    if not batch_ids or len(batch_ids) > MAX_BATCHES:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"1 to {MAX_BATCHES} batch ids", status_code=422)
    q = (select(InvoiceLineBatch, InvoiceLine, Invoice)
         .join(InvoiceLine, InvoiceLine.id == InvoiceLineBatch.line_id).join(Invoice, Invoice.id == InvoiceLine.invoice_id)
         .where(InvoiceLineBatch.batch_id.in_(batch_ids), Invoice.status.in_(("completed", "cancelling")))
         .order_by(Invoice.completed_at.desc()))  # fmt: skip
    if not actor.is_owner:
        q = q.where(Invoice.branch_id.in_(list(actor.branch_ids) or [UUID(int=0)]))
    patients = actor.is_owner or actor.has("prescriptions.view")
    out = []
    for b, line, inv in (await session.execute(q)).all():
        customer = await session.get(KnownCustomer, inv.customer_id) if inv.customer_id else None
        row = {
            "invoice_id": inv.id, "number": inv.number, "branch_id": inv.branch_id, "completed_at": inv.completed_at,
            "sku": line.sku, "name": line.name, "batch_id": b.batch_id, "lot_no": b.lot_no,
            "qty_base": b.qty_base - b.returned_qty_base,
            "customer": {"id": customer.id, "name": customer.name, "phone": customer.phone} if customer else None,
        }  # fmt: skip
        if patients and line.patient_id:
            row["patient"] = {"id": line.patient_id, "name_en": line.patient_name_en, "name_km": line.patient_name_km,
                              "prescription_number": line.prescription_number}  # fmt: skip
        out.append(row)
    return out
