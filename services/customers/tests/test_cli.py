from customers_service.cli import republish

from .conftest import create_customer, outbox


async def test_republish_resends_every_customer(client) -> None:
    c = await create_customer(client, name="Sok Dara")
    before = len(await outbox())
    assert await republish() == 1
    new = (await outbox())[before:]
    assert [t for t, _ in new] == ["customer.updated"]
    assert new[0][1]["customer_id"] == c["id"] and new[0][1]["name"] == "Sok Dara"
