from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from auth_service.db import db
from auth_service.models import RefreshToken, User

from .conftest import PREFIX, login, make_user, outbox_types


async def do_refresh(client, token: str):
    return await client.post(f"{PREFIX}/refresh", json={"refresh_token": token})


async def test_refresh_returns_a_new_pair(client) -> None:
    await make_user()
    first = (await login(client)).json()
    r = await do_refresh(client, first["refresh_token"])
    assert r.status_code == 200
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"] != first["access_token"]


async def test_refresh_token_lasts_7_days(client) -> None:
    await make_user()
    before = datetime.now(UTC)
    await login(client)
    async with db.sessionmaker() as session:
        row = (await session.execute(RefreshToken.__table__.select())).first()
    assert timedelta(days=6, hours=23) < row.expires_at - before < timedelta(days=7, minutes=1)


async def test_used_refresh_token_cannot_be_used_again(client) -> None:
    await make_user()
    first = (await login(client)).json()
    await do_refresh(client, first["refresh_token"])
    r = await do_refresh(client, first["refresh_token"])
    assert r.status_code == 401
    assert r.json()["code"] == "SESSION_REVOKED"


async def test_reuse_of_rotated_token_ends_the_whole_session(client) -> None:
    await make_user()
    stolen = (await login(client)).json()["refresh_token"]
    legit = (await do_refresh(client, stolen)).json()["refresh_token"]
    # the attacker replays the old token: the legitimate new one dies too
    assert (await do_refresh(client, stolen)).status_code == 401
    assert (await do_refresh(client, legit)).status_code == 401
    assert "session.reuse_detected" in await outbox_types()


async def test_other_logins_survive_a_reuse_attack(client) -> None:
    await make_user()
    phone_session = (await login(client, ip="10.0.0.1")).json()["refresh_token"]
    stolen = (await login(client, ip="10.0.0.2")).json()["refresh_token"]
    await do_refresh(client, stolen)
    await do_refresh(client, stolen)
    assert (await do_refresh(client, phone_session)).status_code == 200


async def test_expired_refresh_token_is_refused(client) -> None:
    await make_user()
    token = (await login(client)).json()["refresh_token"]
    async with db.sessionmaker() as session, session.begin():
        await session.execute(
            update(RefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    r = await do_refresh(client, token)
    assert r.status_code == 401
    assert r.json()["code"] == "SESSION_REVOKED"


async def test_deactivated_user_cannot_refresh(client) -> None:
    user = await make_user()
    token = (await login(client)).json()["refresh_token"]
    async with db.sessionmaker() as session, session.begin():
        await session.execute(update(User).where(User.id == user.id).values(is_active=False))
    assert (await do_refresh(client, token)).status_code == 401


async def test_unknown_refresh_token_is_refused(client) -> None:
    r = await do_refresh(client, "not-a-real-token")
    assert r.status_code == 401
    assert r.json()["code"] == "NOT_AUTHENTICATED"


async def test_refresh_token_is_stored_only_as_a_hash(client) -> None:
    await make_user()
    token = (await login(client)).json()["refresh_token"]
    async with db.sessionmaker() as session:
        row = (await session.execute(RefreshToken.__table__.select())).first()
    assert row.token_hash != token
    assert len(row.token_hash) == 64
