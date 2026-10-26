import hashlib
import json

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from pharmacy_shared.errors import register_error_handlers
from pharmacy_shared.idempotency import IdempotencyMiddleware, require_idempotency_key
from pharmacy_shared.redis import RedisProvider
from pharmacy_shared.testing import TEST_REDIS_URL

USER = {"X-User-Id": "11111111-1111-1111-1111-111111111111"}


class Sale(BaseModel):
    amount: int


def make_app(redis_url: str = TEST_REDIS_URL) -> tuple[FastAPI, dict[str, int]]:
    calls = {"sales": 0, "fail": 0}
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/sales", status_code=201)
    async def create_sale(sale: Sale, _: str = Depends(require_idempotency_key)) -> dict[str, int]:
        calls["sales"] += 1
        return {"sale_no": calls["sales"], "amount": sale.amount}

    @app.post("/notes")
    async def create_note() -> dict[str, int]:
        calls["sales"] += 1
        return {"n": calls["sales"]}

    @app.post("/flaky")
    async def flaky() -> JSONResponse:
        calls["fail"] += 1
        return JSONResponse({"error": "boom"}, status_code=503)

    app.add_middleware(IdempotencyMiddleware, redis=RedisProvider(redis_url), service="test", ttl_seconds=60)
    return app, calls


@pytest.fixture(autouse=True)
async def clean_redis():
    client = Redis.from_url(TEST_REDIS_URL)
    await client.flushdb()
    yield
    await client.flushdb()
    await client.aclose()


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_retry_with_same_key_returns_saved_response_and_runs_once() -> None:
    app, calls = make_app()
    headers = {**USER, "Idempotency-Key": "sale-0001-abcd"}
    async with client_for(app) as c:
        first = await c.post("/sales", json={"amount": 5}, headers=headers)
        second = await c.post("/sales", json={"amount": 5}, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json() == {"sale_no": 1, "amount": 5}
    assert second.headers["idempotent-replayed"] == "true"
    assert "idempotent-replayed" not in first.headers
    assert calls["sales"] == 1


async def test_same_key_with_different_body_is_rejected() -> None:
    app, calls = make_app()
    headers = {**USER, "Idempotency-Key": "sale-0002-abcd"}
    async with client_for(app) as c:
        await c.post("/sales", json={"amount": 5}, headers=headers)
        r = await c.post("/sales", json={"amount": 9}, headers=headers)
    assert r.status_code == 422
    assert r.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert calls["sales"] == 1


async def test_keys_are_per_user() -> None:
    app, calls = make_app()
    other = {"X-User-Id": "22222222-2222-2222-2222-222222222222"}
    async with client_for(app) as c:
        await c.post("/sales", json={"amount": 5}, headers={**USER, "Idempotency-Key": "same-key-123"})
        r = await c.post("/sales", json={"amount": 5}, headers={**other, "Idempotency-Key": "same-key-123"})
    assert r.json()["sale_no"] == 2
    assert calls["sales"] == 2


async def test_key_still_running_returns_409() -> None:
    app, calls = make_app()
    body = json.dumps({"amount": 5}).encode()
    fp = hashlib.sha256(b"POST /sales\n" + body).hexdigest()
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.set(
        f"idem:test:{USER['X-User-Id']}:sale-0003-abcd", json.dumps({"state": "running", "fp": fp})
    )
    await redis.aclose()
    async with client_for(app) as c:
        r = await c.post(
            "/sales",
            content=body,
            headers={**USER, "Idempotency-Key": "sale-0003-abcd", "Content-Type": "application/json"},
        )
    assert r.status_code == 409
    assert r.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert calls["sales"] == 0


async def test_required_key_missing_returns_400() -> None:
    app, calls = make_app()
    async with client_for(app) as c:
        r = await c.post("/sales", json={"amount": 5}, headers=USER)
    assert r.status_code == 400
    assert r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert calls["sales"] == 0


async def test_invalid_key_returns_400() -> None:
    app, _ = make_app()
    async with client_for(app) as c:
        r = await c.post("/sales", json={"amount": 5}, headers={**USER, "Idempotency-Key": "bad key!"})
    assert r.status_code == 400
    assert r.json()["code"] == "IDEMPOTENCY_KEY_INVALID"


async def test_requests_without_key_are_not_deduplicated() -> None:
    app, calls = make_app()
    async with client_for(app) as c:
        await c.post("/notes", headers=USER)
        await c.post("/notes", headers=USER)
    assert calls["sales"] == 2


async def test_server_errors_are_not_saved_so_retry_runs_again() -> None:
    app, calls = make_app()
    headers = {**USER, "Idempotency-Key": "flaky-0001-abcd"}
    async with client_for(app) as c:
        assert (await c.post("/flaky", headers=headers)).status_code == 503
        assert (await c.post("/flaky", headers=headers)).status_code == 503
    assert calls["fail"] == 2


async def test_redis_down_refuses_instead_of_risking_double_sale() -> None:
    app, calls = make_app("redis://localhost:1/0")
    async with client_for(app) as c:
        r = await c.post("/sales", json={"amount": 5}, headers={**USER, "Idempotency-Key": "sale-0009-abcd"})
    assert r.status_code == 503
    assert r.json()["code"] == "TEMPORARILY_UNAVAILABLE"
    assert calls["sales"] == 0
