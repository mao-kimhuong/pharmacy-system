async def test_health(client) -> None:
    response = await client.get("/api/auth/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "auth"}


async def test_unknown_route_is_404(client) -> None:
    assert (await client.get("/api/auth/v1/does-not-exist")).status_code == 404
