"""Dashboard and reports. Every report: GET /api/reports/v1/<key> with the common
filters; ?format=csv|xlsx|pdf exports the same rows (without hidden cost columns),
rate-limited to 10 per minute per user and written to the User Log."""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.audit import record_audit
from pharmacy_shared.auth import CurrentUser, current_user, requires
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalClient

from ..config import get_settings
from ..db import db
from ..models import OutboxEvent
from ..services import exports
from ..services.common import Ctx, Filters, Result, branch_scope, drop_hidden, make_filters, may_see
from ..services.dashboard import dashboard
from ..services.reports import REPORTS, Report

router = APIRouter()
EXPORTS_PER_MINUTE = 10


@router.get("/dashboard", tags=["dashboard"])
async def get_dashboard(
    branch_id: UUID | None = None,
    user: CurrentUser = Depends(requires("dashboard.view")),
    session: AsyncSession = Depends(db.session),
) -> dict:
    """Today vs yesterday vs the same weekday last week. No branch_id: all your
    branches (the owner: all). gross_profit only with finance.cost_profit."""
    return await dashboard(session, branch_scope(user, branch_id), may_see(user, "cost"))


def allowed(user: CurrentUser, rep: Report) -> bool:
    return all(user.has_any(*p.split("|")) for p in rep.permissions)


@router.get("/catalog", tags=["reports"])
async def catalog(user: CurrentUser = Depends(current_user)) -> list[dict]:
    """The reports this user may open."""
    return [{"key": r.key, "title": r.title, "path": f"/api/reports/v1/{r.key}"}
            for r in REPORTS.values() if allowed(user, r)]  # fmt: skip


class Params:
    def __init__(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        branch_id: UUID | None = None,
        staff_id: UUID | None = None,
        category_id: UUID | None = None,
        supplier_id: UUID | None = None,
        customer_id: UUID | None = None,
        medicine_id: UUID | None = None,
        by: str | None = Query(default=None, description="sales/summary: day|branch|staff|medicine|category|payment_method"),
        within: int | None = Query(default=None, ge=1, le=730, description="expiry: days ahead"),
        status: str | None = Query(default=None, description="expiry: expired"),
        days: int | None = Query(default=None, ge=1, le=730, description="slow-moving: no sale for N days"),
        batch_id: UUID | None = None,
        type: str | None = Query(default=None, max_length=20, description="movements: movement type"),
        method: str | None = Query(default=None, max_length=12, description="payments: method"),
        changed_only: bool = False,
        page: int = Query(default=1, ge=1),
        size: int = Query(default=100, ge=1, le=100),
        format: Literal["json", "csv", "xlsx", "pdf"] = "json",
    ) -> None:
        extra = {"by": by, "within": within, "status": status, "days": days, "batch_id": batch_id, "type": type,
                 "method": method, "changed_only": changed_only or None}  # fmt: skip
        self.filters_kw = {"branch_id": branch_id, "staff_id": staff_id, "category_id": category_id,
                           "supplier_id": supplier_id, "customer_id": customer_id, "medicine_id": medicine_id,
                           "extra": {k: v for k, v in extra.items() if v is not None}}  # fmt: skip
        self.date_from, self.date_to = date_from, date_to
        self.page, self.size, self.format = page, size, format


async def _rate_limit(request: Request, user: CurrentUser) -> None:
    redis = request.app.state.redis.client()
    key = f"reports:exports:{user.id}"
    n = await redis.incr(key)
    if n == 1:
        await redis.expire(key, 60)
    if n > EXPORTS_PER_MINUTE:
        raise AppError(ErrorCode.RATE_LIMITED, f"At most {EXPORTS_PER_MINUTE} exports a minute", status_code=429)


def get_document() -> InternalClient:
    s = get_settings()
    return InternalClient(s.document_url, s.service_name, s.service_token, read_timeout=60)


async def run(rep: Report, p: Params, request: Request, user: CurrentUser, session: AsyncSession,
              document: InternalClient) -> Response | dict:  # fmt: skip
    if not allowed(user, rep):
        missing = next(x for x in rep.permissions if not user.has_any(*x.split("|")))
        raise AppError(ErrorCode.FORBIDDEN, f"You need {missing.replace('|', ' or ')} for this report",
                       status_code=403, details={"permission": missing})  # fmt: skip
    f: Filters = make_filters(p.date_from, p.date_to, **p.filters_kw)
    settings = get_settings()
    exporting = p.format != "json"
    if exporting:
        await _rate_limit(request, user)
        cap = settings.export_pdf_max_rows if p.format == "pdf" else settings.export_max_rows
        ctx = Ctx(session, user, f, branch_scope(user, f.branch_id), cap + 1, 0)
    else:
        ctx = Ctx(session, user, f, branch_scope(user, f.branch_id), p.size, (p.page - 1) * p.size)
    result: Result = drop_hidden(user, await rep.build(ctx))
    if not exporting:
        return {"report": rep.key, "title": result.title, "filters": f.as_dict(), "page": p.page, "size": p.size,
                "total": result.total, "columns": [c.__dict__ for c in result.columns], "rows": result.rows,
                "summary": result.summary}  # fmt: skip
    if len(result.rows) > cap:
        raise AppError(ErrorCode.EXPORT_TOO_LARGE, f"{result.total} rows: at most {cap} in one {p.format.upper()} "
                       "file; narrow the dates or filters", status_code=422,
                       details={"rows": result.total, "max": cap})  # fmt: skip
    if p.format == "csv":
        body = exports.to_csv(result)
    elif p.format == "xlsx":
        body = exports.to_xlsx(result)
    else:
        body = await exports.to_pdf(document, result, f, user.id)
    record_audit(session, OutboxEvent, service="reports", action="report.exported", entity_type="report",
                 entity_id=rep.key, actor=user, branch_id=f.branch_id,
                 after={"format": p.format, "rows": len(result.rows), **f.as_dict()})  # fmt: skip
    await session.commit()
    name = rep.key.replace("/", "-")
    return Response(body, media_type=exports.MEDIA[p.format], headers={
        "Content-Disposition": f'attachment; filename="{name}-{f.date_from}-{f.date_to}.{p.format}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})  # fmt: skip


def _route(rep: Report) -> None:
    async def endpoint(
        request: Request,
        p: Params = Depends(),
        user: CurrentUser = Depends(current_user),
        session: AsyncSession = Depends(db.session),
        document: InternalClient = Depends(get_document),
    ) -> Response | dict:
        return await run(rep, p, request, user, session, document)

    perms = " and ".join(x.replace("|", " or ") for x in rep.permissions)
    router.add_api_route(f"/{rep.key}", endpoint, methods=["GET"], tags=["reports"], name=rep.key, response_model=None,
                         summary=rep.title, description=f"{(rep.build.__doc__ or '').strip()}\n\nNeeds {perms}.")  # fmt: skip


for _rep in REPORTS.values():
    _route(_rep)
