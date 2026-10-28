from .conftest import CASHIER, MANAGER, OWNER, PREFIX, audits, create_customer, outbox


async def test_phone_is_normalized_and_unique(client) -> None:
    c = await create_customer(client, phone="+855 12 345 678")
    assert c["phone"] == "012345678" and c["balance"] == "0.00" and c["available_credit"] == "100.00"
    r = await client.post(f"{PREFIX}/customers", json={"phone": "012-345-678", "name": "x"}, headers=OWNER)
    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_PHONE"
    r = await client.post(f"{PREFIX}/customers", json={"phone": "hello123", "name": "x"}, headers=OWNER)
    assert r.status_code == 422
    found = (await client.get(f"{PREFIX}/customers", params={"q": "855 12 345 678"}, headers=CASHIER)).json()
    assert found["total"] == 1


async def test_only_owner_and_manager_set_credit_limits(client) -> None:
    r = await client.post(f"{PREFIX}/customers", json={"phone": "011222333", "name": "a", "credit_limit": "50"},
                          headers=CASHIER)  # fmt: skip
    assert r.status_code == 403
    r = await client.post(f"{PREFIX}/customers", json={"phone": "011222333", "name": "a"}, headers=CASHIER)
    assert r.status_code == 201  # no credit: fine for a cashier
    c = r.json()
    r = await client.patch(f"{PREFIX}/customers/{c['id']}", json={"credit_limit": "50"}, headers=CASHIER)
    assert r.status_code == 403
    r = await client.patch(f"{PREFIX}/customers/{c['id']}", json={"note": "VIP"}, headers=CASHIER)
    assert r.status_code == 200
    r = await client.patch(f"{PREFIX}/customers/{c['id']}", json={"credit_limit": "50"}, headers=MANAGER)
    assert r.json()["credit_limit"] == "50.00"
    audit = (await audits())[-1]
    assert audit["before"] == {"credit_limit": "0.00"} and audit["after"] == {"credit_limit": "50.00"}


async def test_deactivate_with_reason_never_delete(client) -> None:
    c = await create_customer(client)
    assert (
        await client.post(f"{PREFIX}/customers/{c['id']}/deactivate", json={}, headers=OWNER)
    ).status_code == 422
    r = await client.post(f"{PREFIX}/customers/{c['id']}/deactivate", json={"reason": "moved"}, headers=OWNER)
    assert r.json()["is_active"] is False
    assert (await client.delete(f"{PREFIX}/customers/{c['id']}", headers=OWNER)).status_code == 405
    assert [t for t, _ in await outbox() if t.startswith("customer.")] == [
        "customer.created",
        "customer.deactivated",
    ]


async def test_customer_groups_store_a_default_discount(client) -> None:
    r = await client.post(f"{PREFIX}/customer-groups", json={"name_en": "Clinic", "default_discount_pct": "5"},
                          headers=OWNER)  # fmt: skip
    g = r.json()
    assert g["default_discount_pct"] == "5.00"
    c = await create_customer(client, group_id=g["id"])
    assert c["group"]["name_en"] == "Clinic"
    r = await client.post(f"{PREFIX}/customer-groups", json={"name_en": "Clinic", "default_discount_pct": "101"},
                          headers=OWNER)  # fmt: skip
    assert r.status_code == 422
