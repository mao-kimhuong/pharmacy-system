from uuid import uuid4

import httpx
import pytest
from fastapi import APIRouter, Depends

from pharmacy_shared.app_factory import create_service_app
from pharmacy_shared.auth import CurrentUser
from pharmacy_shared.config import BaseServiceSettings
from pharmacy_shared.db import Database
from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller, InternalClient, internal_caller
from pharmacy_shared.testing import TEST_REDIS_URL

TOKEN = "t" * 40


def make_app(environment: str = "local", token: str = TOKEN):
    settings = BaseServiceSettings(_env_file=None, service_name="inventory", api_prefix="/api/inventory/v1",
                                   redis_url=TEST_REDIS_URL, service_token=token, environment=environment,
                                   outbox_relay_enabled=False, database_url="postgresql+asyncpg://x:y@localhost/z")  # fmt: skip
    internal = APIRouter()

    @internal.post("/echo")
    async def echo(body: dict, caller: InternalCaller = Depends(internal_caller)) -> dict:
        if body.get("fail"):
            raise AppError(ErrorCode.OUT_OF_STOCK, "Only 1 left", status_code=409, details={"available": 1})
        return {"service": caller.service, "user_id": str(caller.user_id), "branch_id": str(caller.branch_id)}

    return create_service_app(settings, Database(settings.database_url), APIRouter(), "test",
                              internal_router=internal)  # fmt: skip


def client_for(app, token: str = TOKEN) -> InternalClient:
    return InternalClient("http://inventory:8000", "sales", token, transport=httpx.ASGITransport(app=app))


ACTOR = CurrentUser(id=uuid4(), role="cashier", branch_ids=frozenset(), is_pharmacist=False)


async def test_internal_call_carries_service_user_and_branch() -> None:
    app = make_app()
    branch = uuid4()
    out = await client_for(app).post(
        "/echo", {}, actor=ACTOR, branch_id=branch, idempotency_key="key-12345678"
    )
    assert out == {"service": "sales", "user_id": str(ACTOR.id), "branch_id": str(branch)}


@pytest.mark.parametrize("token", ["", "wrong-token-of-forty-characters-xxxxxxxx", TOKEN[:-1]])
async def test_a_wrong_or_missing_token_is_401(token) -> None:
    app = make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x") as c:
        r = await c.post("/internal/v1/echo", json={}, headers={"X-Service-Token": token} if token else {})
    assert r.status_code == 401


async def test_errors_come_back_as_the_same_app_error() -> None:
    with pytest.raises(AppError) as exc:
        await client_for(make_app()).post("/echo", {"fail": True})
    assert (exc.value.code, exc.value.status_code, exc.value.details) == (
        ErrorCode.OUT_OF_STOCK,
        409,
        {"available": 1},
    )


async def test_unreachable_service_is_503_after_retries() -> None:
    calls = 0

    def refuse(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    client = InternalClient("http://inventory:8000", "sales", TOKEN, transport=httpx.MockTransport(refuse))
    with pytest.raises(AppError) as exc:
        await client.post("/echo", {})
    assert exc.value.code == ErrorCode.TEMPORARILY_UNAVAILABLE and exc.value.status_code == 503
    assert calls == 3  # first try + 2 retries


async def test_a_read_timeout_is_not_retried() -> None:
    calls = 0

    def slow(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    client = InternalClient("http://inventory:8000", "sales", TOKEN, transport=httpx.MockTransport(slow))
    with pytest.raises(AppError):
        await client.post("/echo", {})
    assert calls == 1


async def test_internal_routes_are_not_under_api_hidden_from_docs_and_not_rate_limited() -> None:
    app = make_app()
    headers = {"X-Service-Token": TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://x") as c:
        assert (await c.post("/api/inventory/v1/echo", json={}, headers=headers)).status_code == 404
        # writes are limited to 120 per minute per caller; internal calls are not counted
        for _ in range(130):
            assert (await c.post("/internal/v1/echo", json={}, headers=headers)).status_code == 200
    assert "/internal/v1/echo" not in str(app.openapi())


@pytest.mark.parametrize("token", ["", "change-me-service-token-xxxxxxxxxxxxxxxxx", "short"])
def test_production_refuses_a_weak_service_token(token) -> None:
    with pytest.raises(RuntimeError, match="SERVICE_TOKEN"):
        make_app("production", token)
    make_app("production", "r" * 32)  # fine
