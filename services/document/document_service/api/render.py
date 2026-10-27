from fastapi import APIRouter, Body, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user

from ..db import db
from ..schemas.render import LabelRender, RenderRequest
from ..services import labels, purchase_orders

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
    - `type: purchase_order` (purchasing.order, own branches): the A4 PO. Right
      after the PO is saved, waits up to 5 s for it, then DOCUMENT_NOT_READY (409).
    """
    settings = request.app.state.settings
    if isinstance(body, LabelRender):
        user.require("labels.print")
        items = [(item.pack_unit_id, item.copies) for item in body.items]
        rows = await labels.load_labels(session, items, settings.max_labels)
        pdf, filename = await labels.render_pdf(rows, body.layout), "labels.pdf"
    else:
        user.require("purchasing.order")
        number, pdf = await purchase_orders.render_po(
            session, user, body.purchase_order_id, settings.document_wait_seconds
        )
        filename = f"{number}.pdf"
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )
