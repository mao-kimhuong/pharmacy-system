from uuid import UUID

import pyotp

from .conftest import PREFIX, login, make_user, totp, verify

B1 = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
B2 = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


async def test_verify_without_token_is_401(client) -> None:
    r = await client.get(f"{PREFIX}/verify")
    assert r.status_code == 401
    assert r.json()["code"] == "NOT_AUTHENTICATED"


async def test_verify_returns_identity_headers(client) -> None:
    user = await make_user(role="pharmacist", branches=(B1, B2), is_pharmacist=True)
    token = (await login(client)).json()["access_token"]
    r = await client.get(f"{PREFIX}/verify", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.headers["x-user-id"] == str(user.id)
    assert r.headers["x-role"] == "pharmacist"
    assert set(r.headers["x-branch-ids"].split(",")) == {str(B1), str(B2)}
    assert r.headers["x-is-pharmacist"] == "true"


async def test_owner_has_no_branch_list_and_every_permission(client) -> None:
    secret = pyotp.random_base32()
    await make_user(role="owner", totp_secret=secret)
    mfa = (await login(client)).json()["mfa_token"]
    token = (await client.post(f"{PREFIX}/login/2fa", json={"mfa_token": mfa, "code": totp(secret)})).json()[
        "access_token"
    ]
    r = await verify(client, token)
    assert r.status_code == 200
    assert r.headers["x-role"] == "owner"
    assert r.headers["x-branch-ids"] == ""
    assert r.headers["x-permissions"] == "*"


async def test_cashier_gets_its_role_permissions(client) -> None:
    await make_user(role="cashier", branches=(B1,))
    token = (await login(client)).json()["access_token"]
    perms = set((await verify(client, token)).headers["x-permissions"].split(","))
    assert "pos.sell" in perms
    assert "settings.users" not in perms
    assert "pos.dispense_rx" not in perms


async def test_verify_is_not_rate_limited(client) -> None:
    await make_user()
    token = (await login(client)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(700):  # above the 600 reads/minute user limit
        r = await client.get(f"{PREFIX}/verify", headers=headers)
    assert r.status_code == 200


async def test_me_returns_the_current_user(client) -> None:
    user = await make_user(branches=(B1,))
    r = await client.get(f"{PREFIX}/me", headers={"X-User-Id": str(user.id), "X-Role": "cashier"})
    assert r.status_code == 200
    assert r.json()["branch_ids"] == [str(B1)]


async def test_me_without_identity_is_401(client) -> None:
    assert (await client.get(f"{PREFIX}/me")).status_code == 401


async def test_whoami_shows_the_forwarded_user(client) -> None:
    r = await client.get(
        f"{PREFIX}/whoami",
        headers={
            "X-User-Id": "11111111-1111-1111-1111-111111111111",
            "X-Role": "cashier",
            "X-Branch-Ids": str(B1),
        },
    )
    assert r.status_code == 200
    assert r.json()["branch_ids"] == [str(B1)]
