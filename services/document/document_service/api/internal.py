"""/internal/v1 of the document service (service token; never through Traefik)."""

import base64

from fastapi import APIRouter, Depends

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..schemas.render import TableRender
from ..services import table

router = APIRouter()


@router.post("/render/table")
async def render_table(body: TableRender, caller: InternalCaller = Depends(internal_caller)) -> dict:
    """A report PDF for the reports service (its rows: already without hidden columns)."""
    return {"pdf_base64": base64.b64encode(await table.render(body.model_dump())).decode()}
