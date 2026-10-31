"""The whole invoice as other services see it (invoice.* events): the
document service prints receipts from it, reports (S8) build sales figures.
Events between services carry cost (reports need it)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BranchSettingsCopy, Invoice, KnownBranch, KnownCustomer, SaleReturn


async def invoice_payload(
    session: AsyncSession, inv: Invoice, returns: list[SaleReturn] | None = None
) -> dict[str, Any]:
    branch = await session.get(KnownBranch, inv.branch_id)
    settings = await session.get(BranchSettingsCopy, inv.branch_id)
    customer = await session.get(KnownCustomer, inv.customer_id) if inv.customer_id else None
    return {
        "invoice_id": str(inv.id), "version": inv.version, "number": inv.number, "status": inv.status,
        "branch": {"id": str(inv.branch_id), "code": branch.code if branch else "",
                   "name_en": branch.name_en if branch else "", "name_km": branch.name_km if branch else "",
                   "receipt_header": settings.receipt_header if settings else "",
                   "receipt_footer": settings.receipt_footer if settings else "",
                   "dispensing_label_size": settings.dispensing_label_size if settings else "70x40"},
        "patient_id": str(inv.patient_id) if inv.patient_id else None,
        "customer": {"id": str(customer.id), "name": customer.name, "name_km": customer.name_km,
                     "phone": customer.phone} if customer else None,
        "cashier_id": str(inv.created_by), "completed_at": inv.completed_at.isoformat() if inv.completed_at else None,
        "lines": [{
            "line_no": x.line_no, "line_id": str(x.id), "medicine_id": str(x.medicine_id),
            "pack_unit_id": str(x.pack_unit_id), "sku": x.sku, "name": x.name, "name_km": x.name_km,
            "pack_unit": x.pack_unit, "qty": x.qty, "qty_in_base": x.qty_in_base, "qty_base": x.qty_base,
            "unit_price": str(x.unit_price), "line_total": str(x.line_total), "cost": str(x.cost),
            "returned_qty_base": x.returned_qty_base,
            "rx": {"rx_item_id": str(x.rx_item_id), "prescription_id": str(x.prescription_id),
                   "prescription_number": x.prescription_number, "patient_id": str(x.patient_id),
                   "patient_name_en": x.patient_name_en, "patient_name_km": x.patient_name_km,
                   "doctor_name": x.doctor_name, "dosage": x.dosage, "frequency": x.frequency,
                   "duration_days": x.duration_days, "warnings": x.warnings or [],
                   "is_controlled": x.is_controlled, "patient_id_document": x.patient_id_document,
                   "allergy_override_reason": x.allergy_override_reason,
                   "allergy_override_by": str(x.allergy_override_by) if x.allergy_override_by else None,
                   "warnings_acknowledged_by": str(x.warnings_acknowledged_by) if x.warnings_acknowledged_by else None,
                   "warnings_acknowledged_at": x.warnings_acknowledged_at.isoformat()
                   if x.warnings_acknowledged_at else None} if x.rx_item_id else None,
            "rx_item_id": str(x.rx_item_id) if x.rx_item_id else None,
            "promotion_ids": list(x.promotion_ids or []), "promo_discount": str(x.promo_discount),
            "manual_discount": str(x.manual_discount), "net": str(x.net), "is_hamper": x.is_hamper,
            "order_line_id": str(x.order_line_id) if x.order_line_id else None,
            "staff_id": str(inv.created_by),
            "batch_override": {"batch_id": str(x.batch_override_id), "reason": x.override_reason}
            if x.batch_override_id else None,
            "batches": [{"batch_id": str(b.batch_id), "lot_no": b.lot_no, "expiry_date": b.expiry_date.isoformat(),
                         "qty_base": b.qty_base, "cost_per_base": str(b.cost_per_base)} for b in x.batches],
        } for x in inv.lines],
        "subtotal": str(inv.subtotal), "discount": str(inv.discount), "total": str(inv.total),
        "khr_per_usd": inv.khr_per_usd, "total_khr": inv.total_khr,
        "sale_order_id": str(inv.sale_order_id) if inv.sale_order_id else None,
        "payments": [{"method": p.method, "currency": p.currency, "amount": str(p.amount),
                      "amount_usd": str(p.amount_usd)} for p in inv.payments],
        "paid": str(inv.paid), "credit_amount": str(inv.credit_amount), "change_usd": str(inv.change_usd),
        "change_in": inv.change_in, "change_given_usd": str(inv.change_given_usd),
        "change_given_khr": inv.change_given_khr, "change_rounding_khr": str(inv.change_rounding_khr),
        "returned_total": str(inv.returned_total),
        "cancel_reason": inv.cancel_reason, "cancelled_at": inv.cancelled_at.isoformat() if inv.cancelled_at else None,
        "returns": [{"return_id": str(r.id), "number": r.number, "refund_method": r.refund_method,
                     "refund_usd": str(r.refund_usd), "to_quarantine": r.to_quarantine, "reason": r.reason,
                     "created_at": r.created_at.isoformat() if r.created_at else None,
                     "lines": [{"line_id": str(x.invoice_line_id), "batch_id": str(x.batch_id),
                                "qty_base": x.qty_base, "amount": str(x.amount)} for x in r.lines]}
                    for r in (returns or [])],
    }  # fmt: skip
