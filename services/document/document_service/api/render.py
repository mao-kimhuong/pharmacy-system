from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires

from ..db import db
from ..schemas.render import RenderRequest
from ..services import labels

router = APIRouter(tags=["render"])


@router.post(
    "/render",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The PDF"}},
)
async def render(
    body: RenderRequest,
    request: Request,
    _: CurrentUser = Depends(requires("labels.print")),
    session: AsyncSession = Depends(db.session),
) -> Response:
    """Labels for the given pack units: name in English and Khmer, strength,
    pack unit, price and a Code128 barcode. Returns a PDF."""
    items = [(item.pack_unit_id, item.copies) for item in body.items]
    rows = await labels.load_labels(session, items, request.app.state.settings.max_labels)
    pdf = await labels.render_pdf(rows, body.layout)
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="labels.pdf"'}
    )
