"""Helpers for tests. Tests run against a real PostgreSQL and Redis
(`docker compose -f docker-compose.test.yml up -d`, started by `make test`)."""

import os
import re

import asyncpg

TEST_PG_ADMIN_URL = os.environ.get(
    "TEST_PG_ADMIN_URL", "postgresql://postgres:postgres@localhost:55432/postgres"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:56379/15")

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def test_database_url(name: str) -> str:
    """SQLAlchemy (asyncpg) URL of a test database on the test server."""
    base = TEST_PG_ADMIN_URL.rsplit("/", 1)[0]
    return f"{base.replace('postgresql://', 'postgresql+asyncpg://', 1)}/{name}"


async def recreate_database(name: str) -> str:
    """Drop and create an empty test database. Returns its SQLAlchemy URL."""
    if not _NAME.match(name):
        raise ValueError(f"invalid test database name: {name!r}")
    conn = await asyncpg.connect(TEST_PG_ADMIN_URL)
    try:
        # Identifiers cannot be bound parameters; the name is validated above.
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    return test_database_url(name)
