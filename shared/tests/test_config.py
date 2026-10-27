"""Passwords with any character must work: URLs are built with escaping, and the
Postgres init script passes the password as a psql variable."""

import os
import shutil
import subprocess
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from yarl import URL as YarlURL

from pharmacy_shared.config import BaseServiceSettings, build_amqp_url, build_database_url
from pharmacy_shared.db import Database
from pharmacy_shared.testing import TEST_PG_ADMIN_URL

PASSWORD = "p@ss:w/rd#1?%'$ x"
INIT_SCRIPT = Path(__file__).resolve().parents[2] / "infra/postgres/init/01-create-databases.sh"
ADMIN = make_url(TEST_PG_ADMIN_URL)


def test_database_url_keeps_every_character() -> None:
    url = make_url(build_database_url("db", 5432, "pharmacy_sales", "sales_user", PASSWORD))
    assert (url.host, url.port, url.database, url.username) == ("db", 5432, "pharmacy_sales", "sales_user")
    assert url.password == PASSWORD


def test_amqp_url_keeps_every_character() -> None:
    url = YarlURL(build_amqp_url("rabbitmq", 5672, "pharmacy", PASSWORD))
    assert (url.host, url.port, url.user) == ("rabbitmq", 5672, "pharmacy")
    assert url.password == PASSWORD
    assert url.path == "//"  # default vhost "/" (escaped as %2F)


def test_settings_build_urls_from_parts(monkeypatch) -> None:
    for key in ("DATABASE_URL", "RABBITMQ_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DB_HOST", "postgres")
    monkeypatch.setenv("DB_NAME", "pharmacy_sales")
    monkeypatch.setenv("DB_USER", "sales_user")
    monkeypatch.setenv("DB_PASSWORD", PASSWORD)
    monkeypatch.setenv("RABBITMQ_HOST", "rabbitmq")
    monkeypatch.setenv("RABBITMQ_PASSWORD", PASSWORD)
    settings = BaseServiceSettings(_env_file=None)
    assert make_url(settings.database_url).password == PASSWORD
    assert make_url(settings.database_url).host == "postgres"
    assert YarlURL(settings.rabbitmq_url).password == PASSWORD


def test_database_url_env_overrides_parts(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:1/d")
    monkeypatch.setenv("DB_PASSWORD", PASSWORD)
    assert BaseServiceSettings(_env_file=None).database_url == "postgresql+asyncpg://u:p@h:1/d"


async def _admin() -> asyncpg.Connection:
    return await asyncpg.connect(TEST_PG_ADMIN_URL)


async def _drop(conn: asyncpg.Connection, role: str, database: str | None = None) -> None:
    # Identifiers cannot be bound parameters; these are constants of this test.
    if database:
        await conn.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    await conn.execute(f'DROP ROLE IF EXISTS "{role}"')


async def _can_log_in(user: str, database: str) -> str:
    db = Database(build_database_url(ADMIN.host, ADMIN.port, database, user, PASSWORD))
    try:
        async with db.engine.connect() as conn:
            return (await conn.execute(text("SELECT current_user"))).scalar_one()
    finally:
        await db.dispose()


async def test_service_connects_with_a_password_full_of_symbols() -> None:
    conn = await _admin()
    try:
        await _drop(conn, "pw_test_user")
        await conn.execute("SELECT set_config('pharmacy.test_pw', $1, false)", PASSWORD)
        await conn.execute(
            "DO $$ BEGIN EXECUTE format('CREATE ROLE pw_test_user LOGIN PASSWORD %L',"
            " current_setting('pharmacy.test_pw')); END $$"
        )
        assert await _can_log_in("pw_test_user", "postgres") == "pw_test_user"
    finally:
        await _drop(conn, "pw_test_user")
        await conn.close()


@pytest.mark.skipif(shutil.which("psql") is None, reason="psql not installed (runs in make test-docker)")
async def test_init_script_creates_a_user_with_a_password_full_of_symbols() -> None:
    conn = await _admin()
    await _drop(conn, "pwtest_user", "pharmacy_pwtest")
    try:
        env = {
            **os.environ,
            "PGHOST": ADMIN.host,
            "PGPORT": str(ADMIN.port),
            "PGPASSWORD": ADMIN.password or "",
            "POSTGRES_USER": ADMIN.username,
        }
        # Load the script's create_db function without its list of real services.
        script = 'eval "$(sed \'/^create_db [a-z]/d\' "$0")"; create_db pwtest "$1"'
        subprocess.run(["bash", "-c", script, str(INIT_SCRIPT), PASSWORD], env=env, check=True)
        assert await _can_log_in("pwtest_user", "pharmacy_pwtest") == "pwtest_user"
    finally:
        await _drop(conn, "pwtest_user", "pharmacy_pwtest")
        await conn.close()
