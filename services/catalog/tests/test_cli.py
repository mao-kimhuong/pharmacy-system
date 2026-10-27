from catalog_service.cli import republish

from .conftest import OWNER, PREFIX, create_medicine, outbox


async def test_republish_resends_every_medicine_with_its_current_version(client) -> None:
    m = await create_medicine(client)
    await client.post(f"{PREFIX}/categories", json={"name_en": "Pain"}, headers=OWNER)
    before = len(await outbox())
    assert await republish() == (1, 1)
    new = (await outbox())[before:]
    assert [t for t, _ in new] == ["category.updated", "medicine.updated"]
    assert new[1][1]["medicine_id"] == m["id"] and new[1][1]["version"] == m["version"]
    assert len(new[1][1]["pack_units"]) == 3
