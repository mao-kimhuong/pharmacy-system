"""What every report shares: filters, branch scope, columns (some only for users
who may see cost), paging, and the run of a query into rows.

Cost never leaks: a column marked `secret` is removed from the columns AND from
every row before JSON, CSV, XLSX or the PDF request is produced (drop_hidden).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from pharmacy_shared import clock
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.errors import AppError, ErrorCode

MAX_RANGE_DAYS = 400
# secret → who may see it
SECRETS = {
    "cost": ("finance.cost_profit",),
    "purchase": ("purchasing.order", "purchasing.pay", "finance.cost_profit"),
}


@dataclass(frozen=True)
class Col:
    key: str
    label: str
    kind: str = "text"  # text | money | qty | date | pct | khr
    secret: str | None = None  # cost | purchase


@dataclass
class Filters:
    date_from: date
    date_to: date
    branch_id: UUID | None = None
    staff_id: UUID | None = None
    category_id: UUID | None = None
    supplier_id: UUID | None = None
    customer_id: UUID | None = None
    medicine_id: UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {k: str(v) for k, v in {**self.__dict__, **self.extra}.items() if v not in (None, {}) and k != "extra"}


@dataclass
class Ctx:
    session: AsyncSession
    user: CurrentUser
    f: Filters
    branches: list[UUID] | None  # None = every branch (owner)
    limit: int
    offset: int


@dataclass
class Result:
    title: str
    columns: list[Col]
    rows: list[dict[str, Any]]
    total: int
    summary: dict[str, Any] = field(default_factory=dict)


def make_filters(date_from: date | None, date_to: date | None, **kw: Any) -> Filters:
    today = clock.today()
    to = date_to or today
    start = date_from or (to - timedelta(days=29))
    if start > to:
        raise AppError(ErrorCode.VALIDATION_ERROR, "date_from is after date_to", status_code=422)
    if (to - start).days > MAX_RANGE_DAYS:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"At most {MAX_RANGE_DAYS} days at once", status_code=422)
    return Filters(date_from=start, date_to=to, **kw)


def branch_scope(user: CurrentUser, branch_id: UUID | None) -> list[UUID] | None:
    """The branches a report may read: the one asked for (if the user has it),
    else all of the user's branches; None = every branch (owner)."""
    if branch_id is not None:
        user.require_branch(branch_id)
        return [branch_id]
    if user.is_owner:
        return None
    return sorted(user.branch_ids) or [UUID(int=0)]


def in_branches(column: Any, branches: list[UUID] | None) -> Any:
    return column.in_(branches) if branches is not None else column.is_not(None)


def may_see(user: CurrentUser, secret: str | None) -> bool:
    return secret is None or user.is_owner or user.has_any(*SECRETS[secret])


def drop_hidden(user: CurrentUser, result: Result) -> Result:
    hidden = {c.key for c in result.columns if not may_see(user, c.secret)}
    if not hidden:
        return result
    return Result(
        title=result.title,
        columns=[c for c in result.columns if c.key not in hidden],
        rows=[{k: v for k, v in r.items() if k not in hidden} for r in result.rows],
        total=result.total,
        summary={k: v for k, v in result.summary.items() if k not in hidden},
    )


def plain(value: Any) -> Any:
    """JSON-friendly values: money as strings, dates ISO, UUIDs as strings."""
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.01"))) if value.as_tuple().exponent >= -2 else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


async def run_query(ctx: Ctx, query: Select, columns: list[Col], title: str, total: int | None = None) -> Result:
    """total: when the caller already knows it (cheaper than counting the joined query)."""
    if total is None:
        total = (await ctx.session.execute(select(func.count()).select_from(query.order_by(None).subquery()))).scalar_one()
    rows = (await ctx.session.execute(query.limit(ctx.limit).offset(ctx.offset))).mappings().all()
    keys = [c.key for c in columns]
    return Result(title, columns, [{k: plain(r.get(k)) for k in keys} for r in rows], int(total))


def page(ctx: Ctx, rows: list[dict[str, Any]], columns: list[Col], title: str, **summary: Any) -> Result:
    """For reports computed in Python (small sets): slice after building."""
    keys = [c.key for c in columns]
    shown = rows[ctx.offset: ctx.offset + ctx.limit]
    return Result(title, columns, [{k: plain(r.get(k)) for k in keys} for r in shown], len(rows),
                  {k: plain(v) for k, v in summary.items()})  # fmt: skip


def pct(part: Decimal, whole: Decimal) -> Decimal | None:
    return (part * 100 / whole).quantize(Decimal("0.01")) if whole else None
