from .conftest import PREFIX, login, make_user, outbox_types


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_logout_blocks_the_access_token_and_the_session(client) -> None:
    await make_user()
    tokens = (await login(client)).json()
    r = await client.post(
        f"{PREFIX}/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=bearer(tokens["access_token"]),
    )
    assert r.status_code == 204
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(tokens["access_token"]))).status_code == 401
    refresh = await client.post(f"{PREFIX}/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401
    assert "user.logged_out" in await outbox_types()


async def test_logout_without_body_blocks_the_access_token(client) -> None:
    await make_user()
    access = (await login(client)).json()["access_token"]
    assert (await client.post(f"{PREFIX}/logout", headers=bearer(access))).status_code == 204
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(access))).status_code == 401


async def test_logout_keeps_other_devices_logged_in(client) -> None:
    await make_user()
    pos = (await login(client, ip="10.0.0.1")).json()
    phone = (await login(client, ip="10.0.0.2")).json()
    await client.post(
        f"{PREFIX}/logout", json={"refresh_token": pos["refresh_token"]}, headers=bearer(pos["access_token"])
    )
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(phone["access_token"]))).status_code == 200
    assert (
        await client.post(f"{PREFIX}/refresh", json={"refresh_token": phone["refresh_token"]})
    ).status_code == 200


async def test_logout_all_devices(client) -> None:
    await make_user()
    pos = (await login(client, ip="10.0.0.1")).json()
    phone = (await login(client, ip="10.0.0.2")).json()
    r = await client.post(f"{PREFIX}/logout", json={"all_devices": True}, headers=bearer(pos["access_token"]))
    assert r.status_code == 204
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(phone["access_token"]))).status_code == 401
    assert (
        await client.post(f"{PREFIX}/refresh", json={"refresh_token": phone["refresh_token"]})
    ).status_code == 401
    # logging in again afterwards works
    fresh = (await login(client, ip="10.0.0.3")).json()
    assert (await client.get(f"{PREFIX}/verify", headers=bearer(fresh["access_token"]))).status_code == 200


async def test_logout_cannot_end_someone_elses_session(client) -> None:
    await make_user(phone="011111111")
    await make_user(phone="022222222")
    a = (await login(client, phone="011111111")).json()
    b = (await login(client, phone="022222222")).json()
    await client.post(
        f"{PREFIX}/logout", json={"refresh_token": b["refresh_token"]}, headers=bearer(a["access_token"])
    )
    assert (
        await client.post(f"{PREFIX}/refresh", json={"refresh_token": b["refresh_token"]})
    ).status_code == 200


async def test_logout_needs_a_token(client) -> None:
    r = await client.post(f"{PREFIX}/logout")
    assert r.status_code == 401
