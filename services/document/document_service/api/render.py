from fastapi import APIRouter, Body, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user

from ..db import db
from ..schemas.render import LabelRender, PurchaseOrderRender, RenderRequest
from ..services import labels, purchase_orders, receipts

router = APIRouter(tags=["render"])


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
) -> Response:
    """Returns a PDF.

    - `type: label` (labels.print): name in English and Khmer, strength, pack
      unit, price and a Code128 barcode per pack unit.
    - `type: purchase_order` (purchasing.order, own branches): the A4 PO.
    - `type: receipt_80mm` / `invoice_a4` (pos.sell or sales.view, own branches):
      branch header/footer, USD + KHR totals, payments, change.
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
