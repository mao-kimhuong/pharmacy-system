from branch_service.cli import republish

from .conftest import create, outbox


async def test_republish_resends_every_branch(client) -> None:
    b = await create(client, code="PP1")
    await create(client, code="PP2")
    before = len(await outbox())
    assert await republish() == 2
    new = (await outbox())[before:]
    assert [t for t, _ in new] == ["branch.updated", "branch.settings_updated"] * 2
    assert new[0][1]["branch_id"] == b["id"] and new[0][1]["name_km"] == "សាខា"
