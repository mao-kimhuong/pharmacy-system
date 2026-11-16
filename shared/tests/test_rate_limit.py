import httpx
import pytest
from fastapi import FastAPI

from pharmacy_shared.rate_limit import RateLimitMiddleware
from pharmacy_shared.redis import RedisProvider
from pharmacy_shared.redis import connect as connect_redis
from pharmacy_shared.testing import TEST_REDIS_URL

NOW = 1_800_000_010.0  # 10 seconds into a minute


def make_app(redis_url: str = TEST_REDIS_URL) -> FastAPI:
    app = FastAPI()

    @app.get("/items")
    async def list_items() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/items")
    async def create_item() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware,
        redis=RedisProvider(redis_url),
        service="test",
        reads_per_minute=3,
        writes_per_minute=2,
        exempt_paths=("/health",),
        clock=lambda: NOW,
    )
    return app


@pytest.fixture(autouse=True)
async def clean_redis():
    client = connect_redis(TEST_REDIS_URL)
    await client.flushdb()
    yield
    await client.flushdb()
    await client.aclose()


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_reads_over_limit_get_429_with_retry_after() -> None:
    async with client_for(make_app()) as c:
        user = {"X-User-Id": "11111111-1111-1111-1111-111111111111"}
        for _ in range(3):
            assert (await c.get("/items", headers=user)).status_code == 200
        r = await c.get("/items", headers=user)
    assert r.status_code == 429
    assert r.json()["code"] == "RATE_LIMITED"
    assert r.headers["retry-after"] == "50"


async def test_writes_have_their_own_lower_limit() -> None:
    async with client_for(make_app()) as c:
        user = {"X-User-Id": "11111111-1111-1111-1111-111111111111"}
        assert (await c.post("/items", headers=user)).status_code == 200
        assert (await c.post("/items", headers=user)).status_code == 200
        assert (await c.post("/items", headers=user)).status_code == 429
        # reads are counted separately
        assert (await c.get("/items", headers=user)).status_code == 200


async def test_each_user_has_their_own_counter() -> None:
    async with client_for(make_app()) as c:
        a = {"X-User-Id": "11111111-1111-1111-1111-111111111111"}
        b = {"X-User-Id": "22222222-2222-2222-2222-222222222222"}
        for _ in range(3):
            await c.get("/items", headers=a)
        assert (await c.get("/items", headers=a)).status_code == 429
        assert (await c.get("/items", headers=b)).status_code == 200


async def test_anonymous_requests_are_counted_by_forwarded_ip() -> None:
    async with client_for(make_app()) as c:
        ip1 = {"X-Forwarded-For": "10.0.0.1"}
        for _ in range(3):
            await c.get("/items", headers=ip1)
        assert (await c.get("/items", headers=ip1)).status_code == 429
        assert (await c.get("/items", headers={"X-Forwarded-For": "10.0.0.2"})).status_code == 200


async def test_exempt_paths_are_not_limited() -> None:
    async with client_for(make_app()) as c:
        for _ in range(10):
            assert (await c.get("/health")).status_code == 200


async def test_fails_open_when_redis_is_down() -> None:
    async with client_for(make_app("redis://localhost:1/0")) as c:
        for _ in range(5):
            assert (await c.get("/items")).status_code == 200
