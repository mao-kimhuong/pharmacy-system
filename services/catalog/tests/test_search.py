from .conftest import CASHIER, OWNER, PREFIX, create_medicine


async def search(client, q: str, headers=CASHIER) -> dict:
    r = await client.get(f"{PREFIX}/medicines/search", params={"q": q}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_barcode_match_comes_first_with_the_scanned_pack_unit(client) -> None:
    para = await create_medicine(client, sku="PARA500")
    # a product whose name contains the barcode text must still come after the exact barcode hit
    await create_medicine(client, sku="OTHER1", brand_name="PARA500-B tablets", pack_units=[])
    found = await search(client, "PARA500-B")
    assert found["items"][0]["id"] == para["id"]
    box = next(p for p in para["pack_units"] if p["name"] == "box")
    assert found["items"][0]["matched_pack_unit_id"] == box["id"]
    assert found["items"][1]["matched_pack_unit_id"] is None


async def test_search_by_english_brand_and_generic_name(client) -> None:
    await create_medicine(client, sku="PARA500")
    await create_medicine(client, sku="AMOX500", brand_name="Amoxil", generic_name="Amoxicillin",
                          name_km="អាម៉ុកស៊ីស៊ីលីន", pack_units=[])  # fmt: skip
    assert [m["sku"] for m in (await search(client, "panad"))["items"]] == ["PARA500"]
    assert [m["sku"] for m in (await search(client, "AMOXICILLIN"))["items"]] == ["AMOX500"]


async def test_search_by_khmer_name(client) -> None:
    await create_medicine(client, sku="PARA500")
    await create_medicine(client, sku="AMOX500", brand_name="Amoxil", generic_name="Amoxicillin",
                          name_km="អាម៉ុកស៊ីស៊ីលីន", pack_units=[])  # fmt: skip
    assert [m["sku"] for m in (await search(client, "អាម៉ុក"))["items"]] == ["AMOX500"]
    assert [m["sku"] for m in (await search(client, "ប៉ារ៉ាសេតាម៉ុល"))["items"]] == ["PARA500"]


async def test_search_by_sku(client) -> None:
    await create_medicine(client, sku="PARA500")
    assert [m["sku"] for m in (await search(client, "para500"))["items"]] == ["PARA500"]


async def test_search_skips_inactive_products(client) -> None:
    m = await create_medicine(client)
    await client.post(f"{PREFIX}/medicines/{m['id']}/deactivate", json={"reason": "x"}, headers=OWNER)
    assert (await search(client, "Panadol"))["total"] == 0
    assert (await search(client, "PARA500-B"))["total"] == 0


async def test_search_is_paged(client) -> None:
    for i in range(25):
        await create_medicine(client, sku=f"VITC{i:02d}", brand_name=f"Vitamin C {i}", pack_units=[])
    first = await search(client, "vitamin")
    assert first["total"] == 25 and len(first["items"]) == 20
    r = await client.get(f"{PREFIX}/medicines/search", params={"q": "vitamin", "page": 2}, headers=CASHIER)
    assert len(r.json()["items"]) == 5


async def test_like_wildcards_are_plain_text(client) -> None:
    await create_medicine(client)
    assert (await search(client, "%"))["total"] == 0
    assert (await search(client, "_"))["total"] == 0


async def test_sql_in_the_search_text_is_just_text(client) -> None:
    await create_medicine(client)
    assert (await search(client, "' OR 1=1 --"))["total"] == 0
    assert (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["total"] == 1
