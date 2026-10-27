from .conftest import CASHIER, MANAGER, OWNER, PREFIX, audits, create_supplier, outbox


async def test_create_edit_deactivate_supplier(client) -> None:
    s = await create_supplier(client, code="dksh", name_km="ឌីខេអេសអេច", phone="023 999 000")
    assert s["code"] == "DKSH" and s["payment_terms_days"] == 30 and s["name_km"] == "ឌីខេអេសអេច"
    r = await client.patch(f"{PREFIX}/suppliers/{s['id']}", json={"payment_terms_days": 45}, headers=OWNER)
    assert r.json()["payment_terms_days"] == 45
    r = await client.post(f"{PREFIX}/suppliers/{s['id']}/deactivate", json={}, headers=OWNER)
    assert r.status_code == 422  # reason required
    r = await client.post(
        f"{PREFIX}/suppliers/{s['id']}/deactivate", json={"reason": "closed"}, headers=OWNER
    )
    assert r.json()["is_active"] is False
    assert (await client.get(f"{PREFIX}/suppliers", headers=OWNER)).json()["total"] == 0
    assert (await client.get(f"{PREFIX}/suppliers?include_inactive=true", headers=OWNER)).json()["total"] == 1
    assert [a["action"] for a in await audits()] == [
        "supplier.created",
        "supplier.updated",
        "supplier.deactivated",
    ]
    assert (await audits())[1]["before"] == {"payment_terms_days": 30}
    assert [t for t, _ in await outbox() if t != "audit.recorded"] == [
        "supplier.created", "supplier.updated", "supplier.deactivated",
    ]  # fmt: skip
    assert (await client.delete(f"{PREFIX}/suppliers/{s['id']}", headers=OWNER)).status_code == 405


async def test_supplier_code_is_unique_and_fixed(client) -> None:
    s = await create_supplier(client, code="ZUELLIG")
    r = await client.post(f"{PREFIX}/suppliers", json={"code": "zuellig", "name": "x"}, headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_CODE"
    r = await client.patch(f"{PREFIX}/suppliers/{s['id']}", json={"code": "NEW"}, headers=OWNER)
    assert r.status_code == 422


async def test_supplier_groups_always_work_and_are_logged(client) -> None:
    r = await client.post(f"{PREFIX}/supplier-groups", json={"name_en": "Importer", "name_km": "អ្នកនាំចូល"},
                          headers=OWNER)  # fmt: skip
    assert r.status_code == 201
    g = r.json()
    s = await create_supplier(client, group_id=g["id"])
    assert s["group"]["name_en"] == "Importer"
    r = await client.post(f"{PREFIX}/supplier-groups", json={"name_en": "IMPORTER"}, headers=OWNER)
    assert r.status_code == 409
    assert (await client.get(f"{PREFIX}/suppliers?group_id={g['id']}", headers=OWNER)).json()["total"] == 1
    assert "supplier_group.created" in [a["action"] for a in await audits()]


async def test_cashier_can_read_suppliers_but_not_change_them(client) -> None:
    s = await create_supplier(client)
    assert (await client.get(f"{PREFIX}/suppliers", headers=CASHIER)).status_code == 200
    r = await client.post(f"{PREFIX}/suppliers", json={"code": "X1", "name": "x"}, headers=CASHIER)
    assert r.status_code == 403
    r = await client.patch(f"{PREFIX}/suppliers/{s['id']}", json={"name": "x"}, headers=CASHIER)
    assert r.status_code == 403
    assert (
        await client.patch(f"{PREFIX}/suppliers/{s['id']}", json={"name": "y"}, headers=MANAGER)
    ).status_code == 200
