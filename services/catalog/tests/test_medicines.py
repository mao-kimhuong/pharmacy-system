from uuid import uuid4

import pytest

from .conftest import (
    CASHIER,
    MANAGER,
    OWNER,
    PHARMACIST,
    PREFIX,
    audits,
    create_medicine,
    medicine_body,
    outbox,
)


async def test_create_medicine_with_base_and_bigger_pack_units(client) -> None:
    m = await create_medicine(client, sku="para500")
    assert m["sku"] == "PARA500"  # upper-cased
    assert m["name_km"] == "ប៉ារ៉ាសេតាម៉ុល"
    packs = {p["name"]: p for p in m["pack_units"]}
    assert set(packs) == {"tablet", "strip", "box"}
    assert packs["tablet"]["is_base"] and packs["tablet"]["qty_in_base"] == 1
    assert packs["tablet"]["sell_price"] == "0.10"
    assert [p["is_base"] for p in m["pack_units"]].count(True) == 1
    assert m["is_rx_only"] is False and m["version"] == 1


async def test_cost_is_not_part_of_a_medicine(client) -> None:
    r = await client.post(f"{PREFIX}/medicines", json=medicine_body(cost="0.05"), headers=OWNER)
    assert r.status_code == 422  # extra="forbid": cost lives on batches (inventory)
    m = await create_medicine(client)
    assert not any("cost" in k for k in m) and not any("cost" in k for p in m["pack_units"] for k in p)


async def test_medicine_created_event_has_what_other_services_need(client) -> None:
    m = await create_medicine(client)
    events = await outbox()
    assert [t for t, _ in events] == ["medicine.created", "audit.recorded"]
    payload = events[0][1]
    assert payload["medicine_id"] == m["id"] and payload["version"] == 1
    for key in ("sku", "brand_name", "generic_name", "strength", "dosage_form", "name_km",
                "is_rx_only", "controlled_schedule", "base_unit", "is_active"):  # fmt: skip
        assert key in payload
    box = next(p for p in payload["pack_units"] if p["name"] == "box")
    assert box == {
        "id": box["id"], "name": "box", "qty_in_base": 100, "barcode": "PARA500-B",
        "sell_price": "8.50", "is_base": False, "is_active": True,
    }  # fmt: skip
    audit = events[1][1]
    assert audit["action"] == "medicine.created" and audit["entity_type"] == "medicine"
    assert audit["after"]["pack_units.box.sell_price"] == "8.50"


async def test_controlled_medicine_is_always_rx_only(client) -> None:
    m = await create_medicine(client, sku="DIAZ5", controlled_schedule="IV", pack_units=[])
    assert m["is_rx_only"] is True  # set automatically
    r = await client.post(
        f"{PREFIX}/medicines",
        json=medicine_body("DIAZ10", controlled_schedule="IV", is_rx_only=False, pack_units=[]),
        headers=OWNER,
    )
    assert r.status_code == 422
    r = await client.patch(f"{PREFIX}/medicines/{m['id']}", json={"is_rx_only": False}, headers=OWNER)
    assert r.status_code == 422


async def test_making_a_medicine_controlled_makes_it_rx_only(client) -> None:
    m = await create_medicine(client)
    r = await client.patch(f"{PREFIX}/medicines/{m['id']}", json={"controlled_schedule": "II"}, headers=OWNER)
    assert r.status_code == 200 and r.json()["is_rx_only"] is True


@pytest.mark.parametrize("schedule", ["V", "4", "ii", ""])
async def test_only_schedules_i_to_iv(client, schedule) -> None:
    r = await client.post(
        f"{PREFIX}/medicines", json=medicine_body(controlled_schedule=schedule), headers=OWNER
    )
    assert r.status_code == 422


async def test_sku_is_unique(client) -> None:
    await create_medicine(client)
    r = await client.post(f"{PREFIX}/medicines", json=medicine_body("para500", pack_units=[]), headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_SKU"


async def test_barcodes_are_unique_across_all_pack_units(client) -> None:
    a = await create_medicine(client, sku="A1")
    body = medicine_body("B1", base_barcode="A1-S", pack_units=[])
    r = await client.post(f"{PREFIX}/medicines", json=body, headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_BARCODE"
    b = await create_medicine(client, sku="B1", pack_units=[])
    r = await client.post(
        f"{PREFIX}/medicines/{b['id']}/pack-units",
        json={"name": "box", "qty_in_base": 50, "barcode": "A1-B", "sell_price": "4"},
        headers=OWNER,
    )
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_BARCODE"
    # also against a deactivated pack unit
    strip = next(p for p in a["pack_units"] if p["name"] == "strip")
    await client.post(f"{PREFIX}/pack-units/{strip['id']}/deactivate", json={"reason": "x"}, headers=OWNER)
    base = next(p for p in b["pack_units"] if p["is_base"])
    r = await client.patch(f"{PREFIX}/pack-units/{base['id']}", json={"barcode": "A1-S"}, headers=OWNER)
    assert r.status_code == 409


async def test_same_barcode_twice_in_one_request_is_refused(client) -> None:
    body = medicine_body(base_barcode="SAME-1")
    body["pack_units"][0]["barcode"] = "SAME-1"
    r = await client.post(f"{PREFIX}/medicines", json=body, headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_BARCODE"


async def test_exactly_one_base_unit_with_qty_one(client) -> None:
    body = medicine_body()
    body["pack_units"].append({"name": "piece", "qty_in_base": 1, "sell_price": "0.10"})
    assert (await client.post(f"{PREFIX}/medicines", json=body, headers=OWNER)).status_code == 422
    m = await create_medicine(client)
    base = next(p for p in m["pack_units"] if p["is_base"])
    r = await client.patch(f"{PREFIX}/pack-units/{base['id']}", json={"qty_in_base": 5}, headers=OWNER)
    assert r.status_code == 422
    r = await client.post(f"{PREFIX}/pack-units/{base['id']}/deactivate", json={"reason": "x"}, headers=OWNER)
    assert r.status_code == 422
    r = await client.post(
        f"{PREFIX}/medicines/{m['id']}/pack-units",
        json={"name": "tablet2", "qty_in_base": 1, "sell_price": "0.1"},
        headers=OWNER,
    )
    assert r.status_code == 422


async def test_pack_unit_names_are_unique_per_medicine(client) -> None:
    m = await create_medicine(client)
    r = await client.post(
        f"{PREFIX}/medicines/{m['id']}/pack-units",
        json={"name": "BOX", "qty_in_base": 200, "sell_price": "16"},
        headers=OWNER,
    )
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_NAME"


async def test_renaming_the_base_unit_renames_the_base_pack_unit(client) -> None:
    m = await create_medicine(client)
    r = await client.patch(f"{PREFIX}/medicines/{m['id']}", json={"base_unit": "tab"}, headers=OWNER)
    assert r.status_code == 200
    base = next(p for p in r.json()["pack_units"] if p["is_base"])
    assert base["name"] == "tab"


@pytest.mark.parametrize("price", ["-1", "0.001", "1e20"])
async def test_bad_prices_are_refused(client, price) -> None:
    r = await client.post(f"{PREFIX}/medicines", json=medicine_body(base_price=price), headers=OWNER)
    assert r.status_code == 422


async def test_price_change_is_logged_with_old_and_new_value(client) -> None:
    m = await create_medicine(client)
    box = next(p for p in m["pack_units"] if p["name"] == "box")
    r = await client.patch(f"{PREFIX}/pack-units/{box['id']}", json={"sell_price": "9.00"}, headers=OWNER)
    assert r.status_code == 200 and r.json()["sell_price"] == "9.00"
    audit = (await audits())[-1]
    assert audit["action"] == "pack_unit.updated"
    assert audit["before"] == {"pack_units.box.sell_price": "8.50"}
    assert audit["after"] == {"pack_units.box.sell_price": "9.00"}
    event = [p for t, p in await outbox() if t == "medicine.updated"][-1]
    assert event["version"] == 2


async def test_unchanged_edit_writes_nothing(client) -> None:
    m = await create_medicine(client)
    before = len(await outbox())
    r = await client.patch(f"{PREFIX}/medicines/{m['id']}", json={"brand_name": "Panadol"}, headers=OWNER)
    assert r.status_code == 200 and r.json()["version"] == 1
    assert len(await outbox()) == before


async def test_deactivate_needs_a_reason_and_is_logged(client) -> None:
    m = await create_medicine(client)
    r = await client.post(f"{PREFIX}/medicines/{m['id']}/deactivate", json={}, headers=OWNER)
    assert r.status_code == 422
    r = await client.post(
        f"{PREFIX}/medicines/{m['id']}/deactivate", json={"reason": "Discontinued"}, headers=OWNER
    )
    assert r.status_code == 200 and r.json()["is_active"] is False
    types = [t for t, _ in await outbox()]
    assert types[-2:] == ["medicine.deactivated", "audit.recorded"]
    audit = (await audits())[-1]
    assert audit["after"] == {"is_active": False, "reason": "Discontinued"}
    # still readable, hidden from the default list
    assert (await client.get(f"{PREFIX}/medicines/{m['id']}", headers=OWNER)).status_code == 200
    assert (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["total"] == 0
    listed = await client.get(f"{PREFIX}/medicines?include_inactive=true", headers=OWNER)
    assert listed.json()["total"] == 1
    r = await client.post(f"{PREFIX}/medicines/{m['id']}/activate", headers=OWNER)
    assert r.json()["is_active"] is True
    assert [t for t, _ in await outbox()][-2] == "medicine.activated"


async def test_there_is_no_delete(client) -> None:
    m = await create_medicine(client)
    r = await client.delete(f"{PREFIX}/medicines/{m['id']}", headers=OWNER)
    assert r.status_code == 405


async def test_cashier_and_pharmacist_can_view_but_not_edit(client) -> None:
    m = await create_medicine(client)
    for headers in (CASHIER, PHARMACIST):
        assert (await client.get(f"{PREFIX}/medicines", headers=headers)).status_code == 200
        assert (await client.get(f"{PREFIX}/medicines/{m['id']}", headers=headers)).status_code == 200
        r = await client.post(f"{PREFIX}/medicines", json=medicine_body("X1"), headers=headers)
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
        r = await client.patch(f"{PREFIX}/medicines/{m['id']}", json={"brand_name": "x"}, headers=headers)
        assert r.status_code == 403
        r = await client.post(f"{PREFIX}/categories", json={"name_en": "x"}, headers=headers)
        assert r.status_code == 403


async def test_manager_can_edit(client) -> None:
    m = await create_medicine(client, headers=MANAGER)
    r = await client.patch(f"{PREFIX}/medicines/{m['id']}", json={"reorder_level": 50}, headers=MANAGER)
    assert r.status_code == 200 and r.json()["reorder_level"] == 50


async def test_needs_a_logged_in_user(client) -> None:
    assert (await client.get(f"{PREFIX}/medicines")).status_code == 401


async def test_unknown_category_is_refused(client) -> None:
    r = await client.post(f"{PREFIX}/medicines", json=medicine_body(category_id=str(uuid4())), headers=OWNER)
    assert r.status_code == 422 and r.json()["code"] == "UNKNOWN_CATEGORY"


async def test_medicine_with_category_and_brand(client) -> None:
    cat = (await client.post(f"{PREFIX}/categories", json={"name_en": "Pain & fever", "name_km": "ឈឺ"},
                             headers=OWNER)).json()  # fmt: skip
    brand = (await client.post(f"{PREFIX}/brands", json={"name_en": "GSK"}, headers=OWNER)).json()
    m = await create_medicine(client, category_id=cat["id"], brand_id=brand["id"])
    assert m["category"]["name_en"] == "Pain & fever" and m["brand"]["name_en"] == "GSK"
    filtered = await client.get(f"{PREFIX}/medicines?category_id={cat['id']}", headers=OWNER)
    assert filtered.json()["total"] == 1


async def test_active_ingredients_default_from_generic_and_drug_classes_travel_in_events(client) -> None:
    m = await create_medicine(client, sku="AUGM625", generic_name="Amoxicillin + Clavulanic acid",
                              drug_classes=["penicillins", " Penicillins ", "beta-lactams"], pack_units=[])  # fmt: skip
    assert m["active_ingredients"] == ["Amoxicillin", "Clavulanic acid"]
    assert m["drug_classes"] == ["penicillins", "beta-lactams"]  # duplicates ignoring case dropped
    event = [p for t, p in await outbox() if t == "medicine.created"][-1]
    assert event["active_ingredients"] == ["Amoxicillin", "Clavulanic acid"]
    assert event["drug_classes"] == ["penicillins", "beta-lactams"]
    r = await client.patch(
        f"{PREFIX}/medicines/{m['id']}", json={"drug_classes": ["penicillins"]}, headers=OWNER
    )
    assert r.json()["drug_classes"] == ["penicillins"]
    assert (await audits())[-1]["after"] == {"drug_classes": "penicillins"}
