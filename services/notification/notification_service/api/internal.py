"""/internal/v1 of the notification service (service token; never through Traefik)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.telegram import InternalLinkIn, InternalLinkOut
from ..services import customer_admin

router = APIRouter()


@router.post("/link-tokens", response_model=InternalLinkOut)
async def link_token(body: InternalLinkIn, request: Request, caller: InternalCaller = Depends(internal_caller),
                     session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """The Telegram link printed on a receipt or statement (document service). The same link for the same
    ref while unused; null when there is nothing to link."""
    return {"url": await customer_admin.internal_link(session, request.app.state.settings, body.model_dump())}
