PREFIX = "/api/stockcount/v1"
USER = {
    "X-User-Id": "11111111-1111-1111-1111-111111111111",
    "X-Role": "cashier",
    "X-Branch-Ids": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "X-Is-Pharmacist": "false",
}


async def test_health(client) -> None:
    response = await client.get(f"{PREFIX}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "stockcount"}


async def test_unknown_route_is_404(client) -> None:
    assert (await client.get(f"{PREFIX}/does-not-exist")).status_code == 404


async def test_whoami_needs_a_user(client) -> None:
    response = await client.get(f"{PREFIX}/whoami")
    assert response.status_code == 401
    assert response.json()["code"] == "NOT_AUTHENTICATED"


async def test_whoami_shows_the_user_from_traefik_headers(client) -> None:
    response = await client.get(f"{PREFIX}/whoami", headers=USER)
    assert response.status_code == 200
    assert response.json()["user_id"] == USER["X-User-Id"]
    assert response.json()["branch_ids"] == [USER["X-Branch-Ids"]]
