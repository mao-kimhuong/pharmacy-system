import pytest

from .conftest import CASHIER, OWNER, PREFIX, audits, outbox


@pytest.mark.parametrize("path", ["categories", "brands"])
async def test_create_edit_deactivate(client, path) -> None:
    r = await client.post(f"{PREFIX}/{path}", json={"name_en": "Antibiotics", "name_km": "ថ្នាំអង់ទីប៊ីយោទិច"},
                          headers=OWNER)  # fmt: skip
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["name_km"] == "ថ្នាំអង់ទីប៊ីយោទិច"
    r = await client.patch(f"{PREFIX}/{path}/{row['id']}", json={"name_en": "Antibiotic"}, headers=OWNER)
    assert r.json()["name_en"] == "Antibiotic"
    r = await client.post(f"{PREFIX}/{path}/{row['id']}/deactivate", json={"reason": "merged"}, headers=OWNER)
    assert r.json()["is_active"] is False
    assert (await client.get(f"{PREFIX}/{path}", headers=CASHIER)).json() == []
    assert len((await client.get(f"{PREFIX}/{path}?include_inactive=true", headers=OWNER)).json()) == 1
    kind = "category" if path == "categories" else "brand"
    assert [a["action"] for a in await audits()] == [
        f"{kind}.created",
        f"{kind}.updated",
        f"{kind}.deactivated",
    ]
    assert [t for t, _ in await outbox() if t != "audit.recorded"] == [
        f"{kind}.created", f"{kind}.updated", f"{kind}.deactivated",
    ]  # fmt: skip


@pytest.mark.parametrize("path", ["categories", "brands"])
async def test_english_name_is_unique_ignoring_case(client, path) -> None:
    await client.post(f"{PREFIX}/{path}", json={"name_en": "Vitamins"}, headers=OWNER)
    r = await client.post(f"{PREFIX}/{path}", json={"name_en": "  VITAMINS "}, headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_NAME"


async def test_cashier_cannot_change_categories(client) -> None:
    r = await client.post(f"{PREFIX}/brands", json={"name_en": "x"}, headers=CASHIER)
    assert r.status_code == 403
