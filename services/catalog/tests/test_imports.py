from .conftest import (
    CASHIER,
    MANAGER,
    OWNER,
    PHARMACIST,
    PREFIX,
    SAMPLES,
    audits,
    commit,
    count,
    create_medicine,
    idem,
    outbox,
    product_rows,
    upload,
    xlsx,
)


async def uploaded(client, rows: list[dict], headers=None) -> dict:
    r = await upload(client, xlsx(rows), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def detail(client, import_id: str, **params) -> dict:
    r = await client.get(f"{PREFIX}/imports/{import_id}", params=params, headers=OWNER)
    assert r.status_code == 200, r.text
    return r.json()


def errors_by_row(d: dict) -> dict[int, list[dict]]:
    return {r["row_no"]: r["errors"] for r in d["rows"] if r["errors"]}


# ---------------------------------------------------------------- the sample files


async def test_sample_file_validates_and_commits_20_products(client) -> None:
    r = await upload(client, (SAMPLES / "products-sample.xlsx").read_bytes(), name="products-sample.xlsx")
    assert r.status_code == 201, r.text
    imp = r.json()
    # Only problem: its categories and brands do not exist yet.
    assert imp["status"] == "has_errors"
    assert "Antibiotics" in imp["new_categories"] and "Panadol" in imp["new_brands"]
    d = await detail(client, imp["id"])
    codes = {e["code"] for errs in errors_by_row(d).values() for e in errs}
    assert codes == {"UNKNOWN_CATEGORY", "UNKNOWN_BRAND"}
    assert await count("medicines") == 0  # nothing saved by the upload

    r = await commit(client, imp["id"])
    assert r.status_code == 422 and r.json()["code"] == "IMPORT_HAS_ERRORS"
    assert await count("medicines") == 0

    r = await commit(client, imp["id"], create_missing=True)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "committed" and done["created_count"] == 20 and done["skipped_skus"] == []
    assert await count("medicines") == 20
    assert await count("categories") == len(imp["new_categories"])

    diaz = (await client.get(f"{PREFIX}/medicines/search", params={"q": "Diazepam"}, headers=OWNER)).json()
    assert diaz["items"][0]["controlled_schedule"] == "IV" and diaz["items"][0]["is_rx_only"] is True
    para = (await client.get(f"{PREFIX}/medicines/search", params={"q": "PARA500"}, headers=OWNER)).json()
    assert {p["name"]: p["qty_in_base"] for p in para["items"][0]["pack_units"]} == {
        "tablet": 1, "strip": 12, "box": 120,
    }  # fmt: skip
    assert para["items"][0]["name_km"] == "ប៉ាណាដុល ប៉ារ៉ាសេតាម៉ុល"

    actions = [a["action"] for a in await audits()]
    assert actions.count("medicine.created") == 20
    assert actions.count("category.created") == len(imp["new_categories"])
    assert actions.count("brand.created") == len(imp["new_brands"])
    assert actions[0] == "import.uploaded" and actions[-1] == "import.committed"
    created_cat = next(a for a in await audits() if a["action"] == "category.created")
    assert created_cat["after"]["source"] == "import" and created_cat["after"]["import_id"] == imp["id"]
    committed = (await audits())[-1]["after"]
    assert committed["created"] == 20 and sorted(committed["created_categories"]) == imp["new_categories"]
    assert [t for t, _ in await outbox()].count("medicine.created") == 20


async def test_broken_sample_shows_the_bad_row_and_saves_nothing(client) -> None:
    r = await upload(client, (SAMPLES / "products-sample-broken.xlsx").read_bytes())
    imp = r.json()
    d = await detail(client, imp["id"], errors_only=True)
    bad = [(row["row_no"], e) for row in d["rows"] for e in row["errors"] if e["code"] == "DUPLICATE_BARCODE"]
    assert len(bad) == 1
    row_no, error = bad[0]
    bad_row = next(row for row in d["rows"] if row["row_no"] == row_no)
    assert bad_row["sku"] == "AMOX500" and bad_row["data"]["pack_unit"] == "strip"
    assert "repeats row 3" in error["message"]  # Paracetamol's strip row

    r = await commit(client, imp["id"], create_missing=True)
    assert r.status_code == 422 and r.json()["code"] == "IMPORT_HAS_ERRORS"
    assert await count("medicines") == 0 and await count("categories") == 0

    r = await commit(client, imp["id"], create_missing=True, skip_invalid=True)
    assert r.status_code == 200, r.text
    assert r.json()["created_count"] == 19 and r.json()["skipped_skus"] == ["AMOX500"]


# ---------------------------------------------------------------- row rules


async def test_product_columns_may_repeat_but_must_not_conflict(client) -> None:
    rows = product_rows()
    rows[1].update(brand_name="Amoxil", generic_name="Amoxicillin")  # same as row 2: fine
    rows[2].update(brand_name="Amoxicilin Forte")  # different: error on row 4
    imp = await uploaded(client, rows)
    errors = errors_by_row(await detail(client, imp["id"]))
    assert list(errors) == [4]
    assert errors[4][0]["field"] == "brand_name" and "conflicts with row 2" in errors[4][0]["message"]


async def test_blank_product_columns_mean_same_as_first_row(client) -> None:
    imp = await uploaded(client, product_rows())
    assert imp["status"] == "validated" and imp["error_rows"] == 0
    r = await commit(client, imp["id"])
    assert r.status_code == 200 and r.json()["created_count"] == 1
    m = (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["items"][0]
    assert m["is_rx_only"] is True and len(m["pack_units"]) == 3


async def test_a_new_product_needs_its_base_unit_row(client) -> None:
    rows = product_rows()[1:]  # strip and box only
    rows[0].update(brand_name="Amoxil", generic_name="Amoxicillin", base_unit="capsule")
    errors = errors_by_row(await detail(client, (await uploaded(client, rows))["id"]))
    assert "no row for the base unit 'capsule'" in errors[2][0]["message"]


async def test_qty_one_only_for_the_base_unit(client) -> None:
    rows = product_rows()
    rows[1]["qty_in_base"] = 1
    rows[0]["qty_in_base"] = 2
    errors = errors_by_row(await detail(client, (await uploaded(client, rows))["id"]))
    assert "must have qty_in_base 1" in errors[2][0]["message"]
    assert "only for the base unit" in errors[3][0]["message"]


async def test_controlled_product_must_be_rx_only(client) -> None:
    rows = product_rows(controlled_schedule="4", rx_only="no")
    errors = errors_by_row(await detail(client, (await uploaded(client, rows))["id"]))
    assert errors[2][0]["field"] == "rx_only"
    # blank rx_only: becomes Rx-only by itself
    rows = product_rows(controlled_schedule="4", rx_only="")
    imp = await uploaded(client, rows)
    assert imp["status"] == "validated"
    await commit(client, imp["id"])
    m = (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["items"][0]
    assert m["controlled_schedule"] == "IV" and m["is_rx_only"] is True


async def test_bad_cells_are_row_errors(client) -> None:
    rows = product_rows()
    rows[0].update(storage="fridge", reorder_level="-3")
    rows[1]["sell_price_usd"] = "2,30"
    rows[2]["qty_in_base"] = "ten"
    rows.append({"sku": "bad sku!", "pack_unit": "box"})
    errors = errors_by_row(await detail(client, (await uploaded(client, rows))["id"]))
    assert {e["field"] for e in errors[2]} == {"storage", "reorder_level"}
    assert errors[3][0]["field"] == "sell_price_usd"
    assert errors[4][0]["field"] == "qty_in_base"
    assert errors[5][0]["field"] == "sku"


async def test_barcode_already_used_by_another_product(client) -> None:
    await create_medicine(client, sku="PARA500")
    rows = product_rows()
    rows[2]["barcode"] = "PARA500-B"
    errors = errors_by_row(await detail(client, (await uploaded(client, rows))["id"]))
    assert errors[4][0]["code"] == "DUPLICATE_BARCODE" and "PARA500 (box)" in errors[4][0]["message"]


async def test_existing_categories_match_ignoring_case(client) -> None:
    await client.post(f"{PREFIX}/categories", json={"name_en": "Antibiotics"}, headers=OWNER)
    imp = await uploaded(client, product_rows(category="ANTIBIOTICS"))
    assert imp["status"] == "validated" and imp["new_categories"] == []
    await commit(client, imp["id"])
    assert await count("categories") == 1


async def test_unknown_brand_needs_create_missing(client) -> None:
    imp = await uploaded(client, product_rows(brand="Amoxil"))
    assert imp["new_brands"] == ["Amoxil"]
    errors = errors_by_row(await detail(client, imp["id"]))
    assert errors[2][0]["code"] == "UNKNOWN_BRAND"
    assert (await commit(client, imp["id"])).status_code == 422
    assert (await commit(client, imp["id"], create_missing=True)).status_code == 200
    m = (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["items"][0]
    assert m["brand"]["name_en"] == "Amoxil"


# ---------------------------------------------------------------- updates


async def test_existing_sku_is_updated_and_blank_cells_keep_values(client) -> None:
    imp = await uploaded(client, product_rows())
    await commit(client, imp["id"])
    rows = [
        {"sku": "amox500", "pack_unit": "box", "qty_in_base": 100, "sell_price_usd": "22.50"},
        {"sku": "AMOX500", "pack_unit": "bottle-pack", "qty_in_base": 500, "sell_price_usd": "100"},
    ]
    imp2 = await uploaded(client, rows)
    assert imp2["status"] == "validated"
    assert {r["action"] for r in (await detail(client, imp2["id"]))["rows"]} == {"update"}
    r = await commit(client, imp2["id"])
    assert r.json()["created_count"] == 0 and r.json()["updated_count"] == 1
    m = (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["items"][0]
    packs = {p["name"]: p for p in m["pack_units"]}
    assert packs["box"]["sell_price"] == "22.50" and packs["box"]["barcode"] == "8850003"  # kept
    assert packs["strip"]["sell_price"] == "2.30"  # not in the file: untouched
    assert "bottle-pack" in packs and m["brand_name"] == "Amoxil" and m["version"] == 2
    audit = next(a for a in reversed(await audits()) if a["action"] == "medicine.updated")
    assert audit["before"]["pack_units.box.sell_price"] == "21.00"
    assert audit["after"]["pack_units.box.sell_price"] == "22.50"
    assert audit["after"]["import_id"] == imp2["id"]


async def test_reimporting_the_same_file_changes_nothing(client) -> None:
    content = xlsx(product_rows())
    await commit(client, (await upload(client, content)).json()["id"])
    events = len(await outbox())
    r = await commit(client, (await upload(client, content)).json()["id"])
    assert r.json()["updated_count"] == 0
    new = [t for t, _ in await outbox()][events:]
    assert "medicine.updated" not in new


async def test_commit_checks_again_against_current_data(client) -> None:
    imp = await uploaded(client, product_rows())
    assert imp["status"] == "validated"
    await create_medicine(client, sku="OTHER", base_barcode="8850002", pack_units=[])  # takes a barcode
    r = await commit(client, imp["id"])
    assert r.status_code == 422 and r.json()["code"] == "IMPORT_HAS_ERRORS"
    d = await detail(client, imp["id"])
    assert d["status"] == "has_errors" and errors_by_row(d)[3][0]["code"] == "DUPLICATE_BARCODE"
    assert await count("medicines") == 1


# ---------------------------------------------------------------- commit rules


async def test_commit_needs_an_idempotency_key(client) -> None:
    imp = await uploaded(client, product_rows())
    r = await client.post(f"{PREFIX}/imports/{imp['id']}/commit", json={}, headers=OWNER)
    assert r.status_code == 400 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_retried_commit_is_replayed_and_a_second_commit_refused(client) -> None:
    imp = await uploaded(client, product_rows())
    key = idem()
    first = await client.post(f"{PREFIX}/imports/{imp['id']}/commit", json={}, headers={**OWNER, **key})
    again = await client.post(f"{PREFIX}/imports/{imp['id']}/commit", json={}, headers={**OWNER, **key})
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert await count("medicines") == 1
    r = await commit(client, imp["id"])
    assert r.status_code == 409 and r.json()["code"] == "IMPORT_STATE"


async def test_commit_body_rejects_unknown_fields(client) -> None:
    imp = await uploaded(client, product_rows())
    r = await commit(client, imp["id"], skip_invalid=True, created_by="someone")
    assert r.status_code == 422


async def test_import_list_and_paged_rows(client) -> None:
    imp = await uploaded(client, product_rows())
    listed = (await client.get(f"{PREFIX}/imports", headers=OWNER)).json()
    assert listed["total"] == 1 and listed["items"][0]["file_name"] == "products.xlsx"
    d = await detail(client, imp["id"], size=2, page=2)
    assert d["rows_total"] == 3 and [r["row_no"] for r in d["rows"]] == [4]


# ---------------------------------------------------------------- permissions


async def test_cashier_and_pharmacist_cannot_import(client) -> None:
    content = xlsx(product_rows())
    imp = await uploaded(client, product_rows())
    for headers in (CASHIER, PHARMACIST):
        assert (await upload(client, content, headers=headers)).status_code == 403
        assert (await client.get(f"{PREFIX}/imports/template.xlsx", headers=headers)).status_code == 403
        assert (await client.get(f"{PREFIX}/imports/{imp['id']}", headers=headers)).status_code == 403
        r = await commit(client, imp["id"], headers=headers)
        assert r.status_code == 403
    assert await count("medicines") == 0


async def test_manager_can_import(client) -> None:
    imp = await uploaded(client, product_rows(), headers=MANAGER)
    r = await commit(client, imp["id"], headers=MANAGER)
    assert r.status_code == 200


async def test_import_reads_ingredients_and_drug_classes(client) -> None:
    imp = await uploaded(client, product_rows(drug_classes="penicillins; beta-lactams"))
    await commit(client, imp["id"])
    m = (await client.get(f"{PREFIX}/medicines", headers=OWNER)).json()["items"][0]
    assert m["drug_classes"] == ["penicillins", "beta-lactams"]
    assert m["active_ingredients"] == ["Amoxicillin"]
