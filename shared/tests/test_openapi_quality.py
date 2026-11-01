"""OpenAPI quality, per service app:
- every 2xx response has a schema, and not an untyped free-form object;
- every 4xx/5xx response is ErrorOut (with its codes);
- (best effort) every ErrorCode an endpoint raises itself is listed for it."""

import ast
import importlib
import inspect
import os

import pytest

from pharmacy_shared.openapi_errors import ERROR_REF, flat_routes

os.environ.setdefault("OUTBOX_RELAY_ENABLED", "false")
os.environ.setdefault("EVENT_CONSUMER_ENABLED", "false")
SERVICES = ("auth", "branch", "catalog", "inventory", "stockcount", "prescription", "controlled", "sales",
            "customers", "purchasing", "reports", "notification", "document", "ai")  # fmt: skip
JSON = "application/json"


def _app(service: str):  # noqa: ANN202
    try:
        return importlib.import_module(f"{service}_service.main").app
    except ModuleNotFoundError:
        pytest.skip(f"{service}_service is not installed here")


def _untyped(schema: dict, components: dict) -> bool:
    if "$ref" in schema:
        schema = components[schema["$ref"].rsplit("/", 1)[1]]
    if not schema:
        return True
    return schema.get("type") == "object" and not schema.get("properties") and schema.get("additionalProperties", True) in (True, {})


@pytest.mark.parametrize("service", SERVICES)
def test_every_response_is_typed_and_every_error_is_error_out(service: str) -> None:
    app = _app(service)
    doc = app.openapi()
    components = doc.get("components", {}).get("schemas", {})
    problems = []
    for path, methods in doc["paths"].items():
        for method, op in methods.items():
            for status, resp in op.get("responses", {}).items():
                content = resp.get("content") or {}
                where = f"{method.upper()} {path} {status}"
                if status.startswith("2"):
                    if status == "204" or any(t != JSON for t in content):
                        continue  # no body, or a file (PDF, CSV, XLSX)
                    if JSON not in content or _untyped(content[JSON].get("schema") or {}, components):
                        problems.append(f"{where}: untyped")
                elif status[0] in "45":
                    schema = (content.get(JSON) or {}).get("schema") or {}
                    if ERROR_REF not in str(schema):
                        problems.append(f"{where}: not ErrorOut")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("service", SERVICES)
def test_codes_raised_by_an_endpoint_are_listed(service: str) -> None:
    app = _app(service)
    doc = app.openapi()
    problems = []
    for path, route in flat_routes(app.routes):
        if not route.include_in_schema:
            continue
        fn = inspect.unwrap(route.endpoint)
        try:
            node = ast.parse(inspect.getsource(fn).lstrip())
        except (OSError, TypeError, IndentationError):
            continue
        raised = {sub.args[0].attr for sub in ast.walk(node) if isinstance(sub, ast.Call) and sub.args
                  and isinstance(sub.args[0], ast.Attribute) and isinstance(sub.args[0].value, ast.Name)
                  and sub.args[0].value.id == "ErrorCode"}  # fmt: skip
        for method in route.methods:
            op = doc["paths"].get(path, {}).get(method.lower(), {})
            listed = " ".join(r.get("description", "") for s, r in op.get("responses", {}).items() if s[0] in "45")
            problems += [f"{method} {path}: {code}" for code in raised if code not in listed]
    assert not problems, "\n".join(problems)
