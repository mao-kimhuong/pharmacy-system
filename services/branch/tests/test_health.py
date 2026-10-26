from .conftest import PREFIX, user


async def test_health(client) -> None:
    response = await client.get(f"{PREFIX}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "branch"}


async def test_whoami_shows_permissions(client) -> None:
    response = await client.get(f"{PREFIX}/whoami", headers=user("cashier", permissions="pos.sell"))
    assert response.json()["permissions"] == ["pos.sell"]
