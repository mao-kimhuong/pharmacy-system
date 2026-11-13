"""Branch tests run against a real PostgreSQL + Redis (make test starts them)."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.redis import connect as connect_redis
from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_branch"
os.environ["DATABASE_URL"] = test_database_url(TEST_DB)
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from branch_service.db import db  # noqa: E402
from branch_service.main import app  # noqa: E402
from branch_service.services.branches import sync_features  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/branch/v1"


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    asyncio.run(recreate_database(TEST_DB))
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean() -> AsyncIterator[None]:
    async with db.engine.begin() as conn:
        await conn.execute(text("TRUNCATE branches, branch_settings, feature_switches, outbox CASCADE"))
    async with db.sessionmaker() as session:
        await sync_features(session)
    redis = connect_redis(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def user(role: str = "owner", branches: tuple[UUID, ...] = (), permissions: str = "*") -> dict[str, str]:
    """Headers Traefik passes after /verify."""
    return {
        "X-User-Id": str(uuid4()),
        "X-Role": role,
        "X-Branch-Ids": ",".join(str(b) for b in branches),
        "X-Is-Pharmacist": "false",
        "X-Permissions": permissions,
    }


OWNER = user()
MANAGER_PERMS = "settings.users,settings.branch_settings,settings.audit_log,pos.sell"
CASHIER_PERMS = "pos.sell,sales.view"


async def outbox() -> list[tuple[str, dict]]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT event_type, payload FROM outbox ORDER BY seq"))
        return [(r[0], r[1] if isinstance(r[1], dict) else json.loads(r[1])) for r in rows]


async def create(client, code: str = "PP1", **extra) -> dict:
    body = {"code": code, "name_km": "សាខា", "name_en": f"Branch {code}", **extra}
    r = await client.post(f"{PREFIX}/branches", json=body, headers=OWNER)
    assert r.status_code == 201, r.text
    return r.json()
