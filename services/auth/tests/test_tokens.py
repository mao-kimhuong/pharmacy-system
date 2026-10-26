import time

import jwt

from auth_service.config import get_settings

from .conftest import PREFIX, login, make_user


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_access_token_lasts_15_minutes(client) -> None:
    await make_user()
    token = (await login(client)).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == 15 * 60
    assert claims["type"] == "access"


async def test_expired_token_is_refused(client) -> None:
    user = await make_user()
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "role": "cashier",
            "jti": "x",
            "iat": now - 1000,
            "exp": now - 100,
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    r = await client.get(f"{PREFIX}/verify", headers=bearer(expired))
    assert r.status_code == 401
    assert r.json()["code"] == "NOT_AUTHENTICATED"


async def test_token_signed_with_another_secret_is_refused(client) -> None:
    user = await make_user()
    now = int(time.time())
    forged = jwt.encode(
        {"sub": str(user.id), "type": "access", "role": "owner", "jti": "x", "iat": now, "exp": now + 600},
        "attacker-secret-attacker-secret-attacker",
        algorithm="HS256",
    )
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(forged))).status_code == 401


async def test_unsigned_token_is_refused(client) -> None:
    user = await make_user()
    now = int(time.time())
    none_alg = jwt.encode(
        {"sub": str(user.id), "type": "access", "role": "owner", "jti": "x", "iat": now, "exp": now + 600},
        key=None,
        algorithm="none",
    )
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(none_alg))).status_code == 401


async def test_refresh_token_cannot_be_used_as_access_token(client) -> None:
    await make_user()
    refresh = (await login(client)).json()["refresh_token"]
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(refresh))).status_code == 401
