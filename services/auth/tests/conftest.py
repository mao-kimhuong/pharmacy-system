"""Auth tests run against a real PostgreSQL + Redis (make test starts them)."""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

from pharmacy_shared.testing import TEST_REDIS_URL, recreate_database, test_database_url

TEST_DB = "test_auth"
os.environ["DATABASE_URL"] = test_database_url(TEST_DB)
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["OUTBOX_RELAY_ENABLED"] = "false"
os.environ["EVENT_CONSUMER_ENABLED"] = "false"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-hs256-0123456789"

import httpx  # noqa: E402
import pyotp  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402

from auth_service.config import get_settings  # noqa: E402
from auth_service.db import db  # noqa: E402
from auth_service.main import app  # noqa: E402
from auth_service.models import KnownBranch, User, UserBranch  # noqa: E402
from auth_service.services.access import load_permissions  # noqa: E402
from auth_service.services.catalog_sync import sync_catalog  # noqa: E402
from auth_service.services.mfa import encrypt_secret  # noqa: E402
from auth_service.services.passwords import hash_password  # noqa: E402

SERVICE_DIR = Path(__file__).resolve().parents[1]
PREFIX = "/api/auth/v1"
PASSWORD = "correct-horse-battery"
B1 = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
B2 = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Fresh database, built with the real migrations (so they are tested too)."""
    asyncio.run(recreate_database(TEST_DB))
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean() -> AsyncIterator[None]:
    async with db.engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE users, user_branches, refresh_tokens, outbox, audit_logs, known_branches,"
                " processed_messages, role_permissions CASCADE"
            )
        )
        await conn.execute(text("DELETE FROM roles WHERE NOT is_system"))
        await conn.execute(text("UPDATE roles SET is_active = true"))
    await sync_catalog()  # built-in roles get their default permissions back
    redis = Redis.from_url(TEST_REDIS_URL)
    await redis.flushdb()
    await redis.aclose()
    yield
    await db.dispose()
    await app.state.redis.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


async def make_user(
    phone: str = "012345678",
    password: str = PASSWORD,
    role: str = "cashier",
    branches: tuple[UUID, ...] = (),
    is_active: bool = True,
    is_pharmacist: bool = False,
    totp_secret: str | None = None,
    name: str = "Test User",
) -> User:
    async with db.sessionmaker() as session, session.begin():
        user = User(
            name=name,
            phone=phone,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            is_pharmacist=is_pharmacist,
            branches=[UserBranch(branch_id=b) for b in branches],
            totp_secret_enc=encrypt_secret(totp_secret, get_settings()) if totp_secret else None,
            totp_enabled=bool(totp_secret),
        )
        session.add(user)
    return user


async def add_branch(branch_id: UUID | None = None, code: str = "PP1", active: bool = True) -> UUID:
    branch_id = branch_id or uuid4()
    async with db.sessionmaker() as session, session.begin():
        session.add(KnownBranch(id=branch_id, code=code, name_en=f"Branch {code}", is_active=active))
    return branch_id


async def as_user(user: User) -> dict[str, str]:
    """The headers Traefik would pass after /verify (for calling admin endpoints)."""
    async with db.sessionmaker() as session:
        perms = await load_permissions(session, user.role)
    return {
        "X-User-Id": str(user.id),
        "X-Role": user.role,
        "X-Branch-Ids": ",".join(str(b) for b in user.branch_ids),
        "X-Is-Pharmacist": "true" if user.is_pharmacist else "false",
        "X-Permissions": ",".join(perms),
    }


def totp(secret: str, steps_ahead: int = 0) -> str:
    return pyotp.TOTP(secret).at(time.time() + 30 * steps_ahead)


async def login(
    client: httpx.AsyncClient, phone: str = "012345678", password: str = PASSWORD, ip: str = "10.0.0.1"
) -> httpx.Response:
    return await client.post(
        f"{PREFIX}/login", json={"phone": phone, "password": password}, headers={"X-Forwarded-For": ip}
    )


async def verify(
    client: httpx.AsyncClient, access_token: str, uri: str = "/api/sales/v1/whoami"
) -> httpx.Response:
    return await client.get(
        f"{PREFIX}/verify", headers={"Authorization": f"Bearer {access_token}", "X-Forwarded-Uri": uri}
    )


async def outbox_types() -> list[str]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT event_type FROM outbox ORDER BY seq"))
        return [r[0] for r in rows]


async def audit_actions() -> list[str]:
    async with db.engine.connect() as conn:
        rows = await conn.execute(text("SELECT action FROM audit_logs ORDER BY seq"))
        return [r[0] for r in rows]
