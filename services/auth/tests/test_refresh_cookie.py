"""Web app refresh token: with `X-Refresh-Cookie: 1` the refresh token travels only in an httpOnly,
Secure, SameSite=Strict cookie scoped to /api/auth/v1/refresh, never in the JSON body."""

from .conftest import PASSWORD, PREFIX, make_user, totp

COOKIE = {"X-Refresh-Cookie": "1"}


def refresh_cookie(response) -> tuple[str, str]:  # noqa: ANN001
    """(token, the whole Set-Cookie header) of the refresh cookie."""
    header = next(h for h in response.headers.get_list("set-cookie") if h.startswith("pharmacy_refresh="))
    return header.split(";", 1)[0].split("=", 1)[1], header


async def web_login(client, ip: str = "10.0.2.1"):  # noqa: ANN001, ANN201
    return await client.post(
        f"{PREFIX}/login", json={"phone": "012345678", "password": PASSWORD},
        headers={**COOKIE, "X-Forwarded-For": ip},
    )  # fmt: skip


async def test_web_login_puts_the_refresh_token_only_in_a_strict_cookie(client) -> None:
    await make_user(role="cashier")
    r = await web_login(client)
    assert r.status_code == 200 and r.json()["access_token"]
    assert "refresh_token" not in r.json()
    token, header = refresh_cookie(r)
    attrs = [a.strip().lower() for a in header.split(";")[1:]]
    assert token and "httponly" in attrs and "secure" in attrs and "samesite=strict" in attrs
    assert "path=/api/auth/v1/refresh" in attrs
    assert any(a.startswith("max-age=") and int(a.split("=")[1]) == 7 * 86400 for a in attrs)


async def test_refresh_from_the_cookie_rotates_it(client) -> None:
    await make_user(role="cashier")
    first, _ = refresh_cookie(await web_login(client))
    r = await client.post(f"{PREFIX}/refresh", headers={**COOKIE, "Cookie": f"pharmacy_refresh={first}"})
    assert r.status_code == 200 and r.json()["access_token"] and "refresh_token" not in r.json()
    second, _ = refresh_cookie(r)
    assert second != first
    # the old token is spent: reusing it fails (and revokes the family, as for body tokens)
    reused = await client.post(f"{PREFIX}/refresh", headers={**COOKIE, "Cookie": f"pharmacy_refresh={first}"})
    assert reused.status_code == 401


async def test_refresh_without_body_or_cookie_is_401(client) -> None:
    r = await client.post(f"{PREFIX}/refresh")
    assert r.status_code == 401 and r.json()["code"] == "NOT_AUTHENTICATED"


async def test_other_clients_keep_the_token_in_the_body_and_get_no_cookie(client) -> None:
    await make_user(role="cashier")
    r = await client.post(f"{PREFIX}/login", json={"phone": "012345678", "password": PASSWORD})
    assert r.json()["refresh_token"]
    assert not any(h.startswith("pharmacy_refresh=") for h in r.headers.get_list("set-cookie"))
    again = await client.post(f"{PREFIX}/refresh", json={"refresh_token": r.json()["refresh_token"]})
    assert again.status_code == 200 and again.json()["refresh_token"]


async def test_two_factor_login_also_uses_the_cookie(client) -> None:
    await make_user(role="owner")
    setup = (await web_login(client)).json()["access_token"]
    auth = {"Authorization": f"Bearer {setup}"}
    secret = (await client.post(f"{PREFIX}/2fa/setup", headers=auth)).json()["secret"]
    assert (await client.post(f"{PREFIX}/2fa/enable", json={"code": totp(secret)}, headers=auth)).status_code == 200
    step1 = (await web_login(client, ip="10.0.2.9")).json()
    r = await client.post(
        f"{PREFIX}/login/2fa", json={"mfa_token": step1["mfa_token"], "code": totp(secret, steps_ahead=1)}, headers=COOKIE
    )
    assert r.status_code == 200 and "refresh_token" not in r.json()
    assert refresh_cookie(r)[0]


async def test_logout_clears_the_cookie_and_ends_the_session(client) -> None:
    await make_user(role="cashier")
    r = await web_login(client)
    token, _ = refresh_cookie(r)
    out = await client.post(f"{PREFIX}/logout", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert out.status_code == 204
    cleared = next(h for h in out.headers.get_list("set-cookie") if h.startswith("pharmacy_refresh="))
    assert "max-age=0" in cleared.lower() and "path=/api/auth/v1/refresh" in cleared.lower()
    # the browser could not send the cookie to /logout, so the session (refresh family) is ended by its sid
    again = await client.post(f"{PREFIX}/refresh", headers={"Cookie": f"pharmacy_refresh={token}"})
    assert again.status_code == 401
