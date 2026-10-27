import io

from openpyxl import Workbook

from .conftest import MANAGER, OWNER, PP1, PREFIX, add_product, audits, idem, scalar, stock_of, user


def line(product: dict, **extra) -> dict:
    return {"medicine_id": product["id"], "pack_unit_id": product["box"], "lot_no": "OB1",
            "expiry_date": "2028-03-31", "qty": 3, "unit_cost": "4.00", **extra}  # fmt: skip


async def create(client, lines: list[dict], headers=OWNER) -> dict:
    r = await client.post(
        f"{PREFIX}/opening-balances", json={"branch_id": str(PP1), "lines": lines}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


async def commit(client, opening: dict, headers=OWNER):
    return await client.post(
        f"{PREFIX}/opening-balances/{opening['id']}/commit", headers={**headers, **idem()}
    )


async def test_lines_are_validated_and_nothing_is_saved_until_commit(client) -> None:
    para = await add_product()
    ob = await create(client, [line(para), line(para, expiry_date="2026-01-01", lot_no="OLD"),
                               line(para, lot_no="OB1")])  # fmt: skip
    assert ob["status"] == "has_errors" and ob["error_lines"] == 2
    assert ob["lines"][1]["errors"][0]["code"] == "BATCH_EXPIRED"
    assert "same medicine, lot, expiry and cost as line 1" in ob["lines"][2]["errors"][0]["message"]
    assert await scalar("SELECT count(*) FROM movements") == 0
    r = await commit(client, ob)
    assert r.status_code == 422 and r.json()["code"] == "OPENING_HAS_ERRORS"
    assert await scalar("SELECT count(*) FROM movements") == 0


async def test_commit_books_opening_stock_once_and_locks_the_branch(client) -> None:
    para = await add_product()
    amox = await add_product("AMOX500")
    ob = await create(client, [line(para), line(amox, lot_no="K7", expiry_date="2027-01-31", qty=1)])
    assert ob["status"] == "validated" and ob["lines"][1]["short_expiry"] is True
    r = await commit(client, ob)
    assert r.status_code == 200 and r.json()["status"] == "committed"
    assert {i["sku"]: i["qty_on_hand"] for i in await stock_of(client)} == {"PARA500": 300, "AMOX500": 100}
    assert await scalar("SELECT count(*) FROM movements WHERE type = 'opening'") == 2
    r = await commit(client, ob)
    assert r.status_code == 409
    r = await client.post(f"{PREFIX}/opening-balances", json={"branch_id": str(PP1), "lines": [line(para)]},
                          headers=OWNER)  # fmt: skip
    assert r.status_code == 409 and r.json()["code"] == "INITIALIZE_LOCKED"
    locks = (await client.get(f"{PREFIX}/initialize-locks", headers=OWNER)).json()
    assert locks[0]["locked"] is True
    assert [a["action"] for a in await audits()] == ["opening.validated", "opening.committed"]


async def test_only_the_owner_unlocks_with_a_reason(client) -> None:
    para = await add_product()
    await commit(client, await create(client, [line(para)]))
    r = await client.post(
        f"{PREFIX}/initialize-locks/{PP1}/unlock", json={"reason": "missed a shelf"}, headers=MANAGER
    )
    assert r.status_code == 403
    r = await client.post(f"{PREFIX}/initialize-locks/{PP1}/unlock", json={}, headers=OWNER)
    assert r.status_code == 422
    r = await client.post(
        f"{PREFIX}/initialize-locks/{PP1}/unlock", json={"reason": "missed a shelf"}, headers=OWNER
    )
    assert r.status_code == 200 and r.json()["locked"] is False
    assert (await audits())[-1]["after"] == {"locked": False, "reason": "missed a shelf"}
    ob = await create(client, [line(para, lot_no="OB2")])
    assert (await commit(client, ob)).status_code == 200


async def test_upload_by_sku_and_pack_unit_name(client) -> None:
    await add_product()
    wb = Workbook()
    ws = wb.active
    ws.title = "Opening stock"
    ws.append(["SKU", "Pack Unit", "Lot No", "Expiry Date", "Qty", "Unit Cost USD"])
    ws.append(["para500", "Strip", "S9", "31/03/2028", 7, 0.45])
    ws.append(["NOPE", "box", "X", "2028-03-31", 1, 1])
    out = io.BytesIO()
    wb.save(out)
    r = await client.post(f"{PREFIX}/opening-balances/upload", data={"branch_id": str(PP1)},
                          files={"file": ("opening.xlsx", out.getvalue())}, headers=OWNER)  # fmt: skip
    assert r.status_code == 201, r.text
    ob = r.json()
    assert ob["source"] == "xlsx" and ob["error_lines"] == 1
    assert (ob["lines"][0]["qty_base"], ob["lines"][0]["expiry_date"]) == (70, "2028-03-31")
    assert ob["lines"][1]["errors"][0]["code"] == "UNKNOWN_MEDICINE" and ob["lines"][1]["line_no"] == 3
    r = await client.post(f"{PREFIX}/opening-balances/upload", data={"branch_id": str(PP1)},
                          files={"file": ("x.xlsx", b"not a workbook")}, headers=OWNER)  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "FILE_REJECTED"
    assert (await client.get(f"{PREFIX}/opening-balances/template.xlsx", headers=OWNER)).status_code == 200


async def test_initialize_is_for_the_owner_by_default(client) -> None:
    para = await add_product()
    cashier = user("cashier", "inventory.view,inventory.stock_in")
    r = await client.post(f"{PREFIX}/opening-balances", json={"branch_id": str(PP1), "lines": [line(para)]},
                          headers=cashier)  # fmt: skip
    assert r.status_code == 403
