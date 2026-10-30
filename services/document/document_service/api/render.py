from fastapi import APIRouter, Body, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user
from pharmacy_shared.internal import InternalClient

from ..config import get_settings
from ..db import db
from ..schemas.render import (
    DispensingLabelRender,
    LabelRender,
    PurchaseOrderRender,
    RegisterRender,
    RenderRequest,
    RxSummaryRender,
)
from ..services import dispensing, labels, purchase_orders, receipts
from ..services import register as register_pdf

router = APIRouter(tags=["render"])


def get_controlled() -> InternalClient:
    s = get_settings()
    return InternalClient(s.controlled_url, s.service_name, s.service_token)


@router.post(
    "/render",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The PDF"}},
)
async def render(
    request: Request,
    body: RenderRequest = Body(discriminator="type"),
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
    controlled: InternalClient = Depends(get_controlled),
) -> Response:
    """Returns a PDF.

    - `type: label` (labels.print): name in English and Khmer, strength, pack
      unit, price and a Code128 barcode per pack unit.
    - `type: purchase_order` (purchasing.order, own branches): the A4 PO.
    - `type: receipt_80mm` / `invoice_a4` (pos.sell or sales.view, own branches):
      branch header/footer, USD + KHR totals, payments, change.
    - `type: dispensing_label` (pos.dispense_rx or prescriptions.view, own branches):
      patient, medicine, directions, Rx, lot, pharmacist; Khmer or English; size
      from the branch setting (70×40 mm by default).
    - `type: rx_summary` (prescriptions.view): the patient's allergies and
      prescriptions with what is left; written to the User Log.
    - `type: controlled_register` (controlled.view, own branches): the register as A4
      landscape, per medicine, with the hash-chain check.
    PO and invoice: right after they are saved, waits up to 5 s for them, then
    DOCUMENT_NOT_READY (409).
    """
    settings = request.app.state.settings
    if isinstance(body, LabelRender):
        user.require("labels.print")
        items = [(item.pack_unit_id, item.copies) for item in body.items]
        rows = await labels.load_labels(session, items, settings.max_labels)
        pdf, filename = await labels.render_pdf(rows, body.layout), "labels.pdf"
    elif isinstance(body, PurchaseOrderRender):
        user.require("purchasing.order")
        number, pdf = await purchase_orders.render_po(
            session, user, body.purchase_order_id, settings.document_wait_seconds
        )
        filename = f"{number}.pdf"
    elif isinstance(body, DispensingLabelRender):
        if not user.has_any("pos.dispense_rx", "prescriptions.view"):
            user.require("prescriptions.view")
        number, pdf = await dispensing.render_label(
            session, user, body.invoice_id, body.line_no, body.size, body.lang, settings.document_wait_seconds
        )
        filename = f"{number}-label.pdf"
    elif isinstance(body, RegisterRender):
        user.require("controlled.view")
        pdf = await register_pdf.render(
            controlled, user, body.branch_id, body.medicine_id, body.date_from, body.date_to
        )
        filename = "controlled-register.pdf"
    elif isinstance(body, RxSummaryRender):
        user.require("prescriptions.view")
        name, pdf = await dispensing.render_summary(
            session, user, body.patient_id, settings.document_wait_seconds
        )
        filename = f"{name}.pdf"
    else:
        if not user.has_any("pos.sell", "sales.view"):
            user.require("sales.view")
        number, pdf = await receipts.render(
            session, user, body.invoice_id, body.type, settings.document_wait_seconds
        )
        filename = f"{number}{'-receipt' if body.type == 'receipt_80mm' else ''}.pdf"
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )
