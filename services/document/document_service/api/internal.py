"""/internal/v1 of the document service (service token; never through Traefik)."""

import base64
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.render import TableRender
from ..services import purchase_orders, receipts, statements, table
from .render import get_customers

router = APIRouter()
# The notification service sends these on Telegram after checking the chat and consent itself.
SYSTEM = CurrentUser(id=UUID(int=0), role="owner", branch_ids=frozenset(), is_pharmacist=False,
                     permissions=frozenset({"*"}))  # fmt: skip


class DocRender(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["invoice_a4", "receipt_80mm", "customer_statement", "purchase_order"]
    id: UUID
    lang: Literal["km", "en"] = "km"


@router.post("/render/table")
async def render_table(body: TableRender, caller: InternalCaller = Depends(internal_caller)) -> dict:
    """A report PDF for the reports service (its rows: already without hidden columns)."""
    return {"pdf_base64": base64.b64encode(await table.render(body.model_dump())).decode()}


@router.post("/render")
async def render_doc(body: DocRender, request: Request, caller: InternalCaller = Depends(internal_caller),
                     session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """A PDF for Telegram (T2): receipts and invoices, statements, POs. No Telegram QR on them (the chat is
    linked already). DOCUMENT_NOT_READY when the copy has not arrived: the sender tries again later."""
    wait = request.app.state.settings.document_wait_seconds
    if body.type == "customer_statement":
        name, pdf = await statements.render_statement(get_customers(), SYSTEM, body.id, None, None, body.lang)
    elif body.type == "purchase_order":
        name, pdf = await purchase_orders.render_po(session, SYSTEM, body.id, wait)
    else:
        name, pdf = await receipts.render(session, SYSTEM, body.id, body.type, wait, body.lang)
    return {"filename": f"{name}.pdf", "pdf_base64": base64.b64encode(pdf).decode()}
