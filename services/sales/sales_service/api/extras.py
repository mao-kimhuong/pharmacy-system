from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires, requires_any
from pharmacy_shared.idempotency import require_idempotency_key
from pharmacy_shared.openapi_errors import SALE_PASSTHROUGH, errors

from ..db import db
from ..models import CommissionRule, KnownCustomer, SaleOrder, SaleTemplate, SuspendedCart
from ..schemas.extras import (
    CartIn,
    CartOut,
    CommissionLineOut,
    CommissionReport,
    ConfirmIn,
    LoadedTemplate,
    OrderInvoiceIn,
    OrderOut,
    PeriodOut,
    PricedCart,
    QuoteIn,
    ReasonIn,
    ResumedCart,
    RuleIn,
    RuleOut,
    TemplateIn,
    TemplateOut,
    TemplateUpdate,
)
from ..schemas.preview import CartPreviewIn, CartPreviewOut
from ..schemas.sales import InvoiceOut
from ..services import carts, commission, orders, templates
from ..services.cart import price_cart
from ..services.clients import Clients, get_clients
from ..services.common import branch_for
from ..services.preview import preview
from .sales import respond

router = APIRouter()
suspend = requires("sales.suspend")
order_perm = requires("sales.orders")
template_perm = requires("sales.templates")


@router.post("/carts/preview", response_model=CartPreviewOut, response_model_exclude_none=True, tags=["carts"])
async def cart_preview(
    body: CartPreviewIn, user: CurrentUser = Depends(requires("pos.sell")),
    session: AsyncSession = Depends(db.session), clients: Clients = Depends(get_clients),
) -> dict:  # fmt: skip
    """What posting this cart would do, without doing it: prices and promotions, the
    batches FEFO would take, every hard stop, requirement and warning (English and
    Khmer), KHR total. The same checks as POST /invoices; nothing is saved or held."""
    return await preview(session, user, clients, body.model_dump())


@router.post("/carts/price", response_model=PricedCart, tags=["carts"], deprecated=True)
async def price(
    body: CartIn, user: CurrentUser = Depends(requires("pos.sell")), session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Deprecated: use /carts/preview (removed in S9). List price, best promotion deal, manual discounts, net."""
    await branch_for(session, user, body.branch_id)
    customer = await session.get(KnownCustomer, body.customer_id) if body.customer_id else None
    lines = await price_cart(session, body.branch_id, customer, body.model_dump()["lines"])
    subtotal = sum((x.line_total for x in lines), Decimal("0.00"))
    total = sum((x.net for x in lines), Decimal("0.00"))
    return {
        "lines": [x.as_dict() for x in lines],
        "subtotal": subtotal,
        "discount": subtotal - total,
        "total": total,
    }


@router.post("/carts/suspend", response_model=CartOut, status_code=201, tags=["carts"])
async def suspend_cart(
    body: CartIn, user: CurrentUser = Depends(suspend), session: AsyncSession = Depends(db.session),
) -> SuspendedCart:  # fmt: skip
    """Park the cart (no stock reserved); any terminal of the branch can resume it today."""
    return await carts.suspend(session, user, body.model_dump())


@router.get("/carts", response_model=list[CartOut], tags=["carts"])
async def list_carts(
    branch_id: UUID, status: str = Query(default="suspended", pattern="^(suspended|resumed|expired)$"),
    user: CurrentUser = Depends(suspend), session: AsyncSession = Depends(db.session),
) -> list[SuspendedCart]:  # fmt: skip
    return await carts.list_carts(session, user, branch_id, status)


@router.post("/carts/{cart_id}/resume", response_model=ResumedCart, tags=["carts"])
async def resume_cart(
    cart_id: UUID, user: CurrentUser = Depends(suspend), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> dict:  # fmt: skip
    """Prices, promotions and stock checked again; `changes` lists what is different."""
    return await carts.resume(session, user, clients, cart_id)


@router.post("/sale-templates", response_model=TemplateOut, status_code=201, tags=["templates"])
async def create_template(
    body: TemplateIn, user: CurrentUser = Depends(template_perm), session: AsyncSession = Depends(db.session),
) -> SaleTemplate:  # fmt: skip
    return await templates.create(session, user, body.model_dump())


@router.get("/sale-templates", response_model=list[TemplateOut], tags=["templates"])
async def list_templates(
    branch_id: UUID, customer_id: UUID | None = None, user: CurrentUser = Depends(template_perm),
    session: AsyncSession = Depends(db.session),
) -> list[SaleTemplate]:  # fmt: skip
    return await templates.list_templates(session, user, branch_id, customer_id)


@router.patch("/sale-templates/{template_id}", response_model=TemplateOut, tags=["templates"])
async def update_template(
    template_id: UUID, body: TemplateUpdate, user: CurrentUser = Depends(template_perm),
    session: AsyncSession = Depends(db.session),
) -> SaleTemplate:  # fmt: skip
    return await templates.update(session, user, template_id, body.model_dump(exclude_unset=True))


@router.post("/sale-templates/{template_id}/load", response_model=LoadedTemplate, tags=["templates"])
async def load_template(
    template_id: UUID, customer_id: UUID | None = None, user: CurrentUser = Depends(template_perm),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Cart lines priced now (promotions included); the POS may change the quantities."""
    return await templates.load(session, user, template_id, customer_id)


@router.post("/sale-orders", response_model=OrderOut, status_code=201, tags=["sale orders"])
async def create_quote(
    body: QuoteIn, user: CurrentUser = Depends(order_perm), session: AsyncSession = Depends(db.session),
) -> SaleOrder:  # fmt: skip
    """A quote: prices (promotions included) kept for the order."""
    return await orders.create_quote(session, user, body.model_dump())


@router.get("/sale-orders", response_model=list[OrderOut], tags=["sale orders"])
async def list_orders(
    branch_id: UUID, status: str | None = Query(default=None, max_length=18),
    user: CurrentUser = Depends(order_perm), session: AsyncSession = Depends(db.session),
) -> list[SaleOrder]:  # fmt: skip
    return await orders.list_orders(session, user, branch_id, status)


@router.get("/sale-orders/{order_id}", response_model=OrderOut, tags=["sale orders"])
async def get_order(
    order_id: UUID, user: CurrentUser = Depends(order_perm), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> SaleOrder:  # fmt: skip
    o = await orders.get(session, user, order_id, lock=True)
    if await orders.release_if_expired(session, clients, o):
        o = await orders.get(session, user, order_id)
    await session.commit()
    return o


@router.post("/sale-orders/{order_id}/confirm", response_model=OrderOut, tags=["sale orders"], openapi_extra=errors(*SALE_PASSTHROUGH))
async def confirm(
    order_id: UUID, body: ConfirmIn, _: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(order_perm), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> SaleOrder:  # fmt: skip
    """Quote → order: optionally reserve the stock (until reserve_days) and take a deposit."""
    return await orders.confirm(session, user, clients, order_id, body.model_dump())


@router.post(
    "/sale-orders/{order_id}/invoice", response_model=InvoiceOut, status_code=201, tags=["sale orders"], openapi_extra=errors(*SALE_PASSTHROUGH))
async def invoice(
    order_id: UUID, body: OrderInvoiceIn, key: str = Depends(require_idempotency_key),
    user: CurrentUser = Depends(requires("pos.sell")), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> JSONResponse:  # fmt: skip
    """Invoice all or part of the open quantity at the order's prices (the normal sale
    rules apply); pay with the deposit using method "deposit"."""
    inv = await orders.invoice(session, user, clients, order_id, body.model_dump(), key)
    return respond(InvoiceOut.model_validate(inv), user, 201)


@router.post("/sale-orders/{order_id}/cancel", response_model=OrderOut, tags=["sale orders"])
async def cancel(
    order_id: UUID, body: ReasonIn, user: CurrentUser = Depends(order_perm),
    session: AsyncSession = Depends(db.session), clients: Clients = Depends(get_clients),
) -> SaleOrder:  # fmt: skip
    """Releases the stock; the deposit follows the branch setting (credit / refund / forfeit)."""
    return await orders.cancel(session, user, clients, order_id, body.reason)


@router.post("/sale-orders/{order_id}/close", response_model=OrderOut, tags=["sale orders"])
async def close(
    order_id: UUID, user: CurrentUser = Depends(order_perm), session: AsyncSession = Depends(db.session),
    clients: Clients = Depends(get_clients),
) -> SaleOrder:  # fmt: skip
    return await orders.close(session, user, clients, order_id)


@router.post("/sale-orders/{order_id}/ready", response_model=OrderOut, tags=["sale orders"])
async def ready(
    order_id: UUID, user: CurrentUser = Depends(order_perm), session: AsyncSession = Depends(db.session),
) -> SaleOrder:  # fmt: skip
    """Ready for pickup (ordered / partly fulfilled): the customer gets a Telegram message with what is
    left to pay (if linked and they allow order messages). Again later: a new message."""
    return await orders.mark_ready(session, user, order_id)


@router.post("/commission/rules", response_model=RuleOut, status_code=201, tags=["commission"])
async def create_rule(
    body: RuleIn, user: CurrentUser = Depends(requires("commission.manage")),
    session: AsyncSession = Depends(db.session),
) -> CommissionRule:  # fmt: skip
    return await commission.create_rule(session, user, body.model_dump())


@router.get("/commission/rules", response_model=list[RuleOut], tags=["commission"])
async def list_rules(
    user: CurrentUser = Depends(requires("commission.manage")), session: AsyncSession = Depends(db.session),
) -> list[CommissionRule]:  # fmt: skip
    return await commission.list_rules(session, user)


@router.post("/commission/rules/{rule_id}/deactivate", response_model=RuleOut, tags=["commission"])
async def deactivate_rule(
    rule_id: UUID, user: CurrentUser = Depends(requires("commission.manage")),
    session: AsyncSession = Depends(db.session),
) -> CommissionRule:  # fmt: skip
    return await commission.set_rule_active(session, user, rule_id, False)


@router.post("/commission/periods/{branch_id}/{month}/close", response_model=PeriodOut, tags=["commission"])
async def close_period(
    branch_id: UUID, month: date, user: CurrentUser = Depends(requires("commission.manage")),
    session: AsyncSession = Depends(db.session),
) -> object:  # fmt: skip
    """Locks the month: later returns go to the next open period."""
    return await commission.set_period(session, user, branch_id, month, "closed")


@router.post("/commission/periods/{branch_id}/{month}/paid", response_model=PeriodOut, tags=["commission"])
async def pay_period(
    branch_id: UUID, month: date, user: CurrentUser = Depends(requires("commission.manage")),
    session: AsyncSession = Depends(db.session),
) -> object:  # fmt: skip
    return await commission.set_period(session, user, branch_id, month, "paid")


@router.get("/commission/report", tags=["commission"], response_model=CommissionReport)
async def report(
    branch_id: UUID, month: date, staff_id: UUID | None = None,
    user: CurrentUser = Depends(requires_any("commission.view_own", "commission.manage")),
    session: AsyncSession = Depends(db.session),
) -> dict:  # fmt: skip
    """Per staff for the month; your own only with commission.view_own."""
    return await commission.report(session, user, branch_id, month, staff_id)


@router.get("/commission/report/{staff_id}", response_model=list[CommissionLineOut], tags=["commission"])
async def drill_down(
    staff_id: UUID, branch_id: UUID, month: date,
    user: CurrentUser = Depends(requires_any("commission.view_own", "commission.manage")),
    session: AsyncSession = Depends(db.session),
) -> list[object]:  # fmt: skip
    return await commission.drill_down(session, user, branch_id, month, staff_id)
