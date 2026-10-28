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
                   "receipt_footer": settings.receipt_footer if settings else ""},
        "customer": {"id": str(customer.id), "name": customer.name, "name_km": customer.name_km,
                     "phone": customer.phone} if customer else None,
        "cashier_id": str(inv.created_by), "completed_at": inv.completed_at.isoformat() if inv.completed_at else None,
        "lines": [{
            "line_no": x.line_no, "line_id": str(x.id), "medicine_id": str(x.medicine_id),
            "pack_unit_id": str(x.pack_unit_id), "sku": x.sku, "name": x.name, "name_km": x.name_km,
            "pack_unit": x.pack_unit, "qty": x.qty, "qty_in_base": x.qty_in_base, "qty_base": x.qty_base,
            "unit_price": str(x.unit_price), "line_total": str(x.line_total), "cost": str(x.cost),
            "returned_qty_base": x.returned_qty_base,
            "batch_override": {"batch_id": str(x.batch_override_id), "reason": x.override_reason}
            if x.batch_override_id else None,
            "batches": [{"batch_id": str(b.batch_id), "lot_no": b.lot_no, "expiry_date": b.expiry_date.isoformat(),
                         "qty_base": b.qty_base, "cost_per_base": str(b.cost_per_base)} for b in x.batches],
        } for x in inv.lines],
        "subtotal": str(inv.subtotal), "discount": str(inv.discount), "total": str(inv.total),
        "khr_per_usd": inv.khr_per_usd, "total_khr": inv.total_khr,
        "payments": [{"method": p.method, "currency": p.currency, "amount": str(p.amount),
                      "amount_usd": str(p.amount_usd)} for p in inv.payments],
        "paid": str(inv.paid), "credit_amount": str(inv.credit_amount), "change_usd": str(inv.change_usd),
        "change_in": inv.change_in, "change_given_usd": str(inv.change_given_usd),
        "change_given_khr": inv.change_given_khr, "change_rounding_khr": str(inv.change_rounding_khr),
        "returned_total": str(inv.returned_total),
        "cancel_reason": inv.cancel_reason, "cancelled_at": inv.cancelled_at.isoformat() if inv.cancelled_at else None,
        "returns": [{"return_id": str(r.id), "number": r.number, "refund_method": r.refund_method,
                     "refund_usd": str(r.refund_usd), "to_quarantine": r.to_quarantine, "reason": r.reason,
                     "lines": [{"line_id": str(x.invoice_line_id), "batch_id": str(x.batch_id),
                                "qty_base": x.qty_base, "amount": str(x.amount)} for x in r.lines]}
                    for r in (returns or [])],
    }  # fmt: skip
