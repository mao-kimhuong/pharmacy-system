"""Error responses in the OpenAPI documents.

Every error body is ErrorOut: {"code", "message", "details"} (errors.error_body).
Each operation lists, per HTTP status, exactly the codes it can return:

- found automatically: the endpoint's function (with its Depends(...) defaults)
  and, transitively, every function it calls by name in its service package and
  in pharmacy_shared, are read (AST) for AppError(ErrorCode.X, ..., status_code=N)
  (best effort: a call resolves to every function of that name, so the list may
  be a little longer than the truth, never shorter for code written this way);
- declared: `openapi_extra=errors(ErrorCode.X, ...)` on a route adds codes the
  scan cannot see (codes passed through from another service);
- shared, on every protected route: 401 NOT_AUTHENTICATED, 403 FORBIDDEN /
  MFA_SETUP_REQUIRED, 422 VALIDATION_ERROR, 429 RATE_LIMITED, 503
  TEMPORARILY_UNAVAILABLE.
"""

import ast
import importlib
import inspect
import sys
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from .errors import ErrorCode

ERROR_REF = "#/components/schemas/ErrorOut"
SHARED: dict[int, tuple[str, ...]] = {
    401: (ErrorCode.NOT_AUTHENTICATED,),
    403: (ErrorCode.FORBIDDEN, ErrorCode.MFA_SETUP_REQUIRED),
    422: (ErrorCode.VALIDATION_ERROR,),
    429: (ErrorCode.RATE_LIMITED,),
    503: (ErrorCode.TEMPORARILY_UNAVAILABLE,),
}
DEFAULT_STATUS = {ErrorCode.NOT_FOUND: 404, ErrorCode.FORBIDDEN: 403, ErrorCode.BRANCH_FORBIDDEN: 403,
                  ErrorCode.VALIDATION_ERROR: 422, ErrorCode.TEMPORARILY_UNAVAILABLE: 503}  # fmt: skip


class ErrorOut(BaseModel):
    """Every error: a stable code, a message for people, details for programs."""

    code: str = Field(description="One of the codes listed for this status")
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


def errors(*codes: ErrorCode | tuple[ErrorCode, int], status: int | None = None) -> dict[str, Any]:
    """openapi_extra for a route: codes the scan cannot see (e.g. passed through from
    another service), as ErrorCode or (ErrorCode, status). Status: the pair's, the
    given one, else the usual one for the code (400)."""
    out: dict[str, list[str]] = defaultdict(list)
    for item in codes:
        code, st = item if isinstance(item, tuple) else (item, status or DEFAULT_STATUS.get(item, 400))
        out[str(st)].append(code.value)
    return {"x-error-codes": dict(out)}


# Codes other services return through the sale saga and the preview (InternalClient
# hands their AppError back unchanged).
SALE_PASSTHROUGH = (
    (ErrorCode.OUT_OF_STOCK, 409), (ErrorCode.BATCH_EXPIRED, 409), (ErrorCode.BATCH_BLOCKED, 409),
    (ErrorCode.RX_EXPIRED, 422), (ErrorCode.RX_QUANTITY_EXCEEDED, 422), (ErrorCode.PRESCRIPTION_STATE, 409),
    (ErrorCode.ALLERGY_WARNING, 409), (ErrorCode.DUPLICATE_THERAPY_WARNING, 409),
    (ErrorCode.CREDIT_LIMIT_EXCEEDED, 422), (ErrorCode.DEPOSIT_EXCEEDED, 409), (ErrorCode.NOT_FOUND, 404),
    (ErrorCode.PIN_INVALID, 401), (ErrorCode.PIN_REQUIRED, 401),
)  # fmt: skip


# ---------------------------------------------------------------- the scan


class _Index:
    """Functions of some packages: the (code, status) pairs each one raises, and the
    names it calls."""

    def __init__(self, packages: tuple[str, ...]) -> None:
        self.raises: dict[str, set[tuple[str, int]]] = defaultdict(set)
        self.calls: dict[str, set[str]] = defaultdict(set)
        self.nodes: dict[tuple[str, str], ast.AST] = {}
        for package in packages:
            mod = sys.modules.get(package) or importlib.import_module(package)
            for path in Path(mod.__file__).parent.rglob("*.py"):
                rel = path.relative_to(Path(mod.__file__).parent).with_suffix("")
                module = ".".join([package, *[p for p in rel.parts if p != "__init__"]])
                for node in ast.walk(ast.parse(path.read_text())):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.nodes[(module, node.name)] = node
                        raised, called = _scan(node)
                        self.raises[node.name] |= raised
                        self.calls[node.name] |= called

    @cache  # noqa: B019 – one index per process
    def closure(self, name: str) -> frozenset[tuple[str, int]]:
        seen, todo, out = {name}, [name], set()
        while todo:
            n = todo.pop()
            out |= self.raises.get(n, set())
            for callee in self.calls.get(n, ()):
                if callee not in seen and callee in self.raises:
                    seen.add(callee)
                    todo.append(callee)
        return frozenset(out)


def _scan(node: ast.AST) -> tuple[set[tuple[str, int]], set[str]]:
    raised, called = set(), set()
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if name is None:
            continue
        called.add(name)
        code = sub.args[0] if sub.args else None
        # AppError(ErrorCode.X, msg, status_code=N) and helpers called the same way (Checks.add(..., status=N))
        if isinstance(code, ast.Attribute) and isinstance(code.value, ast.Name) and code.value.id == "ErrorCode":
            status = next((k.value.value for k in sub.keywords if k.arg in ("status_code", "status")
                           and isinstance(k.value, ast.Constant)), None)  # fmt: skip
            if status is None and name == "AppError" and len(sub.args) >= 3 and isinstance(sub.args[2], ast.Constant):
                status = sub.args[2].value
            if isinstance(status, int) and status >= 400 or status is None:
                raised.add((code.attr, int(status or DEFAULT_STATUS.get(ErrorCode(code.attr), 400))))
    return raised, called


@cache
def _index(package: str) -> _Index:
    return _Index((package, "pharmacy_shared"))


def route_codes(route: APIRoute) -> dict[int, set[str]]:
    fn = inspect.unwrap(route.endpoint)
    package = fn.__module__.split(".")[0]
    index = _index(package)
    node = index.nodes.get((fn.__module__, fn.__name__))
    found: set[tuple[str, int]] = set()
    if node is not None:
        raised, called = _scan(node)
        found |= raised
        for name in called:
            found |= index.closure(name)
    out: dict[int, set[str]] = defaultdict(set)
    for code, status in found:
        out[status].add(code)
    return out


def _response(codes: set[str]) -> dict[str, Any]:
    return {"description": ", ".join(sorted(codes)), "content": {"application/json": {"schema": {
        "allOf": [{"$ref": ERROR_REF}, {"type": "object", "properties": {"code": {"enum": sorted(codes)}}}]}}}}


def flat_routes(routes: list[Any], prefix: str = "") -> list[tuple[str, APIRoute]]:
    """(full path, route), also inside included routers (newer FastAPI nests them)."""
    out = []
    for route in routes:
        if isinstance(route, APIRoute):
            out.append((prefix + route.path_format, route))
        elif hasattr(route, "original_router"):
            ctx = route.include_context
            if ctx.include_in_schema:
                out += flat_routes(route.original_router.routes, prefix + (ctx.prefix or ""))
    return out


def add_error_responses(schema: dict[str, Any], routes: list[Any], public_paths: set[str]) -> None:
    """Writes the error responses of every operation into an OpenAPI document."""
    schema.setdefault("components", {}).setdefault("schemas", {})["ErrorOut"] = ErrorOut.model_json_schema()
    schema["components"]["schemas"].pop("HTTPValidationError", None)
    schema["components"]["schemas"].pop("ValidationError", None)
    for path, route in flat_routes(routes):
        if not route.include_in_schema:
            continue
        for method in route.methods:
            codes = route_codes(route)
            op = schema["paths"].get(path, {}).get(method.lower())
            if op is None:
                continue
            for status, listed in (op.pop("x-error-codes", None) or {}).items():
                codes[int(status)] |= set(listed)
            if path not in public_paths:
                for status, shared in SHARED.items():
                    codes[status] |= {c.value for c in shared}
            elif route.body_field is not None or route.dependant.query_params:
                codes[422] |= {ErrorCode.VALIDATION_ERROR.value}
            responses = op.setdefault("responses", {})
            for status in [s for s in responses if s[0] in "45"]:
                if int(status) not in codes:
                    codes[int(status)] = {ErrorCode.VALIDATION_ERROR.value} if status == "422" else set()
            for status, listed in sorted(codes.items()):
                if listed:
                    responses[str(status)] = _response(listed)
