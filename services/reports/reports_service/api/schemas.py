"""Response models of the reports: one per report, its rows typed from the report's
own Col(...) declarations (read from services/reports.py, so a new column shows in
the documentation without another edit). Columns only some users may see (cost)
are optional and absent – not null – when hidden (exclude_unset)."""

import ast
import inspect
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from ..services import reports as reports_module

KIND_TYPES: dict[str, Any] = {
    "money": str | None, "pct": str | None, "date": str | None, "qty": int | None, "khr": int | None,
    "text": str | int | bool | None,
}  # fmt: skip


class ColumnOut(BaseModel):
    key: str
    label: str
    kind: str
    secret: str | None


def _cols_of(tree: ast.Module) -> dict[str, list[tuple[str, str, str | None]]]:
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def cols(node: ast.AST, seen: set[str]) -> list[tuple[str, str, str | None]]:
        out = []
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            name = sub.func.id if isinstance(sub.func, ast.Name) else None
            if name == "Col":
                args = [a.value if isinstance(a, ast.Constant) else None for a in sub.args]
                kw = {k.arg: k.value.value for k in sub.keywords if isinstance(k.value, ast.Constant)}
                key = args[0]
                kind = kw.get("kind", args[2] if len(args) > 2 else "text")
                secret = kw.get("secret", args[3] if len(args) > 3 else None)
                if key and (key, kind, secret) not in out:
                    out.append((key, kind or "text", secret))
            elif name in funcs and name not in seen and name.endswith("_cols"):
                out += [c for c in cols(funcs[name], seen | {name}) if c not in out]
        return out

    found = {}
    for fn in funcs.values():
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "id", None) == "report" and dec.args:
                found[dec.args[0].value] = cols(fn, {fn.name})
    return found


COLUMNS = _cols_of(ast.parse(inspect.getsource(reports_module)))


def _model_name(key: str) -> str:
    return "".join(p.capitalize() for p in key.replace("/", "_").replace("-", "_").split("_"))


def page_model(key: str) -> type[BaseModel]:
    fields = {}
    for col, kind, secret in COLUMNS.get(key, []):
        desc = {"cost": "Only with finance.cost_profit", "purchase": "Only with purchasing.order / purchasing.pay "
                "/ finance.cost_profit"}.get(secret or "", "")  # fmt: skip
        fields[col] = (KIND_TYPES.get(kind, Any), Field(default=None, description=desc or None))
    row = create_model(f"{_model_name(key)}Row", __config__=ConfigDict(extra="forbid"), **fields)  # type: ignore[call-overload]
    return create_model(
        f"{_model_name(key)}Page",
        report=(str, ...), title=(str, ...), filters=(dict[str, str], ...), page=(int, ...), size=(int, ...),
        total=(int, Field(description="Rows in all pages")), columns=(list[ColumnOut], ...), rows=(list[row], ...),
        summary=(dict[str, Any], Field(description="Totals of the report (cost ones only with the permission)")),
        cost_hidden=(bool, Field(description="Columns were hidden: the user may not see cost")),
    )  # fmt: skip


class DayFigures(BaseModel):
    date: str
    sales: str
    sales_khr: int
    invoices: int
    average_basket: str
    returns: str
    net_sales: str
    net_sales_khr: int
    gross_profit: str | None = Field(default=None, description="Only with finance.cost_profit (absent otherwise)")
    margin_pct: str | None = None


class TopMedicine(BaseModel):
    sku: str | None
    name: str | None
    qty_base: int
    net: str


class LowStock(BaseModel):
    branch_id: str
    sku: str | None
    name: str | None
    on_hand: int
    reorder_point: int


class Expiring(BaseModel):
    branch_id: str
    sku: str | None
    lot_no: str
    expiry_date: str
    days_left: int
    qty_base: int


class NearExpiry(BaseModel):
    count: int
    soonest: list[Expiring]


class Pending(BaseModel):
    shrinkages: int
    stock_takes: int
    transfer_requests: int
    purchase_requests: int


class Debtor(BaseModel):
    customer: str | None
    owes: str


class Dashboard(BaseModel):
    branch_ids: list[str] | str = Field(description='The branches counted, or "all"')
    today: DayFigures
    yesterday: DayFigures
    same_day_last_week: DayFigures
    top_medicines: list[TopMedicine]
    low_stock: list[LowStock]
    near_expiry: NearExpiry
    open_controlled_discrepancies: int
    pending_approvals: Pending
    top_debtors: list[Debtor]


class CatalogItem(BaseModel):
    key: str
    title: str
    path: str
