from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from auth_service.db import db
from auth_service.models import User

from .conftest import login, make_user, outbox_types


async def fail(client, times: int) -> list[int]:
    # Different IPs, so the 5-per-minute login limit does not interfere.
    return [(await login(client, password="wrong-pass", ip=f"10.1.0.{i}")).status_code for i in range(times)]


async def test_ten_failures_lock_the_account(client) -> None:
    await make_user()
    statuses = await fail(client, 10)
    assert statuses[:9] == [401] * 9
    assert statuses[9] == 423
    assert "user.locked" in await outbox_types()


async def test_locked_account_refuses_even_the_right_password(client) -> None:
    await make_user()
    await fail(client, 10)
    r = await login(client, ip="10.2.0.1")
    assert r.status_code == 423
    assert r.json()["code"] == "ACCOUNT_LOCKED"
    assert "locked_until" in r.json()["details"]


async def test_lock_ends_after_15_minutes(client) -> None:
    user = await make_user()
    await fail(client, 10)
    async with db.sessionmaker() as session, session.begin():
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (await login(client, ip="10.3.0.1")).status_code == 200


async def test_lock_lasts_15_minutes(client) -> None:
    user = await make_user()
    before = datetime.now(UTC)
    await fail(client, 10)
    async with db.sessionmaker() as session:
        locked_until = (await session.get(User, user.id)).locked_until
    assert timedelta(minutes=14, seconds=50) < locked_until - before < timedelta(minutes=15, seconds=10)
