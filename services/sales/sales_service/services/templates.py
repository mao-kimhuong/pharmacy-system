"""Sale templates (sales.templates): saved baskets – a clinic's regular order, a
common regimen – for a branch, or for one customer of it. Loading one gives cart
lines priced now (promotions included); the POS may change the quantities.
Deactivated, never deleted; every change in the User Log."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

from ..models import KnownCustomer, SaleTemplate, SaleTemplateLine
from .cart import pack_for, price_cart
from .common import audit, branch_for, clean


async def _lines(session: AsyncSession, raw: list[dict[str, Any]]) -> list[SaleTemplateLine]:
    out = []
    for i, x in enumerate(raw, start=1):
        await pack_for(session, x["medicine_id"], x["pack_unit_id"], i)
        out.append(
            SaleTemplateLine(
                line_no=i, medicine_id=x["medicine_id"], pack_unit_id=x["pack_unit_id"], qty=x["qty"]
            )
        )
    return out


async def get(session: AsyncSession, actor: CurrentUser, template_id: UUID) -> SaleTemplate:
    t = await session.get(SaleTemplate, template_id)
    if t is None or not actor.can_access_branch(t.branch_id):
        raise AppError(ErrorCode.NOT_FOUND, "Template not found", status_code=404)
    return t


async def create(session: AsyncSession, actor: CurrentUser, data: dict[str, Any]) -> SaleTemplate:
    branch = await branch_for(session, actor, data["branch_id"])
    if data.get("customer_id") and await session.get(KnownCustomer, data["customer_id"]) is None:
        raise AppError(ErrorCode.CUSTOMER_REQUIRED, "Unknown customer", status_code=422)
    t = SaleTemplate(name=clean(data["name"]), branch_id=branch.id, customer_id=data.get("customer_id"),
                     note=clean(data.get("note")), is_active=True, created_by=actor.id,
                     lines=await _lines(session, data["lines"]))  # fmt: skip
    session.add(t)
    await session.flush()
    audit(session, actor, "sale_template.created", "sale_template", t.id, branch_id=branch.id,
          after={"name": t.name, "lines": len(t.lines)})  # fmt: skip
    await session.commit()
    return t


async def update(
    session: AsyncSession, actor: CurrentUser, template_id: UUID, data: dict[str, Any]
) -> SaleTemplate:
    t = await get(session, actor, template_id)
    if data.get("name") is not None:
        t.name = clean(data["name"])
    if data.get("note") is not None:
        t.note = clean(data["note"])
    if data.get("lines") is not None:
        t.lines.clear()
        await session.flush()
        t.lines.extend(await _lines(session, data["lines"]))
    if data.get("is_active") is not None:
        t.is_active = data["is_active"]
    audit(session, actor, "sale_template.updated", "sale_template", t.id, branch_id=t.branch_id,
          after={"name": t.name, "lines": len(t.lines), "active": t.is_active})  # fmt: skip
    await session.commit()
    await session.refresh(t, attribute_names=["lines"])
    return t


async def list_templates(session: AsyncSession, actor: CurrentUser, branch_id: UUID, customer_id: UUID | None
                         ) -> list[SaleTemplate]:  # fmt: skip
    actor.require_branch(branch_id)
    query = select(SaleTemplate).where(SaleTemplate.branch_id == branch_id, SaleTemplate.is_active.is_(True))
    if customer_id:
        query = query.where((SaleTemplate.customer_id.is_(None)) | (SaleTemplate.customer_id == customer_id))
    return list((await session.execute(query.order_by(SaleTemplate.name))).scalars())


async def load(session: AsyncSession, actor: CurrentUser, template_id: UUID, customer_id: UUID | None
               ) -> dict[str, Any]:  # fmt: skip
    t = await get(session, actor, template_id)
    if not t.is_active:
        raise AppError(ErrorCode.NOT_FOUND, "This template is deactivated", status_code=404)
    customer = (
        await session.get(KnownCustomer, customer_id or t.customer_id)
        if (customer_id or t.customer_id)
        else None
    )
    raw = [{"medicine_id": x.medicine_id, "pack_unit_id": x.pack_unit_id, "qty": x.qty} for x in t.lines]
    priced = await price_cart(session, t.branch_id, customer, raw)
    return {"template_id": t.id, "name": t.name, "customer_id": customer.id if customer else None,
            "lines": [x.as_dict() for x in priced], "total": str(sum((x.net for x in priced), 0))}  # fmt: skip
