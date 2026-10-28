from datetime import date
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.visibility import drop_fields

from ..db import db
from ..models import ExchangeRate, SaleReturn
from ..schemas.sales import (
    InvoiceCreate,
    InvoiceOut,
    InvoicePage,
    RateIn,
    RateOut,
    ReasonRequest,
    ReturnCreate,
    ReturnOut,
)
from ..services import cancel, queries, rates, returns, sale_saga
from ..services.clients import Clients, get_clients
from ..services.common import COST_FIELDS, can_see_cost

router = APIRouter()
view = requires_any("pos.sell", "sales.view")


def respond(model: BaseModel, user: CurrentUser, status_code: int = 200) -> JSONResponse:
    data: Any = model.model_dump(mode="json")
    if not can_see_cost(user):
        data = drop_fields(data, COST_FIELDS)
    return JSONResponse(data, status_code=status_code)


@router.put("/exchange-rates/{branch_id}", response_model=RateOut, tags=["exchange rate"])
async def set_rate(
    branch_id: UUID, body: RateIn, user: CurrentUser = Depends(requires("sales.exchange_rate")),
    session: AsyncSession = Depends(db.session),
) -> ExchangeRate:  # fmt: skip
    """Owner / branch manager. Kept as history (who, when, old → new); logged."""
    return await rates.set_rate(session, user, branch_id, body.khr_per_usd)


@router.get("/exchange-rates/{branch_id}", response_model=list[RateOut], tags=["exchange rate"])
async def rate_history(
    branch_id: UUID, user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
) -> list[ExchangeRate]:
    """Newest first: the first row is the rate in use."""
    return await rates.history(session, user, branch_id)


@router.post("/invoices", response_model=InvoiceOut, status_code=201, tags=["invoices"])
async def create_invoice(
    body: InvoiceCreate,
    key: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("pos.sell")),
    session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> JSONResponse:
    """Sell (the sale saga): validate → reserve stock FEFO → charge credit → confirm
    → number. Any failure undoes what was done; the invoice stays "failed".
    The response shows the batches used per line."""
    inv = await sale_saga.create_invoice(session, user, body.model_dump(), key, clients)
    return respond(InvoiceOut.model_validate(inv), user, 201)


@router.get("/invoices", response_model=InvoicePage, tags=["invoices"])
async def list_invoices(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    branch_id: UUID | None = None,
    staff_id: UUID | None = None,
    customer_id: UUID | None = None,
    status: str | None = Query(
        default=None, pattern="^(pending|completed|failed|cancelling|cancelled|needs_attention)$"
    ),
    number: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(view),
    session: AsyncSession = Depends(db.session),
) -> JSONResponse:
    """List Sale. Your branches only; cost and margin only with finance.cost_profit."""
    f = queries.InvoiceFilter(date_from, date_to, branch_id, staff_id, customer_id, status, number)
    items, total = await queries.list_invoices(session, user, f, page, size)
    return respond(InvoicePage(items=[InvoiceOut.model_validate(i) for i in items], total=total, page=page,
                               size=size), user)  # fmt: skip


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, tags=["invoices"])
async def get_invoice(
    invoice_id: UUID, user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
) -> JSONResponse:
    return respond(InvoiceOut.model_validate(await queries.get_invoice(session, user, invoice_id)), user)


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceOut, tags=["invoices"])
async def cancel_invoice(
    invoice_id: UUID,
    body: ReasonRequest,
    user: CurrentUser = Depends(requires("sales.cancel")),
    session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> JSONResponse:
    """Stock back into the same batches, credit reversed. Today's invoices only
    unless you have sales.cancel_any."""
    inv = await cancel.cancel_invoice(session, user, invoice_id, body.reason, clients)
    return respond(InvoiceOut.model_validate(inv), user)


@router.post("/invoices/{invoice_id}/returns", response_model=ReturnOut, status_code=201, tags=["returns"])
async def create_return(
    invoice_id: UUID,
    body: ReturnCreate,
    _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("sales.return")),
    session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> SaleReturn:
    """Return some lines: refund cash or a credit note; stock back to its batch or to quarantine."""
    return await returns.create_return(session, user, invoice_id, body.model_dump(), clients)


@router.get("/invoices/{invoice_id}/returns", response_model=list[ReturnOut], tags=["returns"])
async def list_returns(
    invoice_id: UUID, user: CurrentUser = Depends(view), session: AsyncSession = Depends(db.session)
) -> list[SaleReturn]:
    inv = await queries.get_invoice(session, user, invoice_id)
    return await queries.returns_of(session, inv.id)
