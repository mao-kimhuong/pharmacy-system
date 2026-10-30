"""S5 in inventory: shelf locations, shrinkage (approval, controlled PIN +
witness, photo), stock-take snapshot / changes since, count adjustments once,
controlled adjust once, movement meta in stock.changed."""

import io
from uuid import uuid4

import pytest
from PIL import Image

from inventory_service.main import app
from inventory_service.services.clients import get_auth, get_storage

from .conftest import (
    INTERNAL,
    PP1,
    PP2,
    PREFIX,
    S3_ENDPOINT,
    add_product,
    event,
    goods_received,
    idem,
    outbox,
    stock_of,
    user,
)  # fmt: skip
from .fake_auth import FakeAuth

MANAGER = user("branch_manager", "inventory.view,inventory.shrinkage,inventory.shrinkage_approve,inventory.locations")
PHARMACIST = user("pharmacist", "inventory.view,inventory.shrinkage")
CASHIER = user("cashier", "inventory.view")


@pytest.fixture
def auth():  # noqa: ANN201
    fake = FakeAuth()
    app.dependency_overrides[get_auth] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_auth, None)


async def stocked(sku: str = "PARA500", qty: int = 100, cost: str = "0.1000", **kw) -> tuple[dict, str]:
    product = await add_product(sku, **kw)
    await event("goods.received", goods_received(product, [("L1", "2028-01-31", qty, cost)]))
    return product, product["id"]


async def batch_of(client, product: dict, branch=PP1) -> str:  # noqa: ANN001
    items = await stock_of(client, branch_id=str(branch))
    for item in items:
        if item["medicine_id"] == product["id"]:
            return item["batches"][0]["batch_id"]
    raise AssertionError("no stock")


async def on_hand(client, product: dict) -> int:  # noqa: ANN001
    items = await stock_of(client, branch_id=str(PP1))
    return sum(i["qty_on_hand"] for i in items if i["medicine_id"] == product["id"])


# ---------------------------------------------------------------- shelf locations


async def test_shelf_location_set_by_manager_and_logged(client) -> None:
    product, _ = await stocked()
    body = {"branch_id": str(PP1), "medicine_id": product["id"], "code": " a3 "}
    assert (await client.put(f"{PREFIX}/shelf-locations", json=body, headers=PHARMACIST)).status_code == 403
    r = await client.put(f"{PREFIX}/shelf-locations", json=body, headers=MANAGER)
    assert r.status_code == 200 and r.json()["code"] == "A3"
    bad = await client.put(f"{PREFIX}/shelf-locations", json={**body, "code": "A 3!"}, headers=MANAGER)
    assert bad.status_code == 422
    other = await client.put(f"{PREFIX}/shelf-locations", json={**body, "branch_id": str(PP2)}, headers=MANAGER)
    assert other.status_code == 403
    rows = (await client.get(f"{PREFIX}/shelf-locations", params={"branch_id": str(PP1)}, headers=MANAGER)).json()
    assert [(x["code"], x["sku"]) for x in rows] == [("A3", "PARA500")]
    assert [p for t, p in await outbox() if t == "audit.recorded"][-1]["action"] == "shelf_location.set"


# ---------------------------------------------------------------- shrinkage


async def test_small_shrinkage_posts_at_once_cost_hidden(client) -> None:
    product, _ = await stocked()
    batch = await batch_of(client, product)
    r = await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()}, json={
        "branch_id": str(PP1), "batch_id": batch, "qty_base": 10, "reason": "damaged", "note": "box fell"})  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "posted" and r.json()["number"] == "PP1-SH-2026-000001"
    assert "value" not in r.json()
    assert await on_hand(client, product) == 90
    changed = [p for t, p in await outbox() if t == "stock.changed"][-1]
    assert changed["type"] == "shrinkage" and changed["delta"] == -10 and changed["meta"]["reason"] == "damaged"


async def test_big_shrinkage_waits_for_someone_else_to_approve(client) -> None:
    product, _ = await stocked(qty=1000, cost="0.2000")
    batch = await batch_of(client, product)
    body = {"branch_id": str(PP1), "batch_id": batch, "qty_base": 300, "reason": "expired"}  # 60 USD > 50
    r = await client.post(f"{PREFIX}/shrinkages", json=body, headers={**MANAGER, **idem()})
    s = r.json()
    assert s["status"] == "pending_approval" and await on_hand(client, product) == 1000
    own = await client.post(f"{PREFIX}/shrinkages/{s['id']}/approve", headers={**MANAGER, **idem()})
    assert own.status_code == 403
    no_perm = await client.post(f"{PREFIX}/shrinkages/{s['id']}/approve", headers={**PHARMACIST, **idem()})
    assert no_perm.status_code == 403
    other = user("branch_manager", "inventory.view,inventory.shrinkage_approve")
    r = await client.post(f"{PREFIX}/shrinkages/{s['id']}/approve", headers={**other, **idem()})
    assert r.json()["status"] == "posted" and await on_hand(client, product) == 700
    again = await client.post(f"{PREFIX}/shrinkages/{s['id']}/approve", headers={**other, **idem()})
    assert again.status_code == 409 and again.json()["code"] == "SHRINKAGE_STATE"
    second = (await client.post(f"{PREFIX}/shrinkages", json=body, headers={**MANAGER, **idem()})).json()
    r = await client.post(f"{PREFIX}/shrinkages/{second['id']}/reject", json={"reason": "found them"}, headers=other)
    assert r.json()["status"] == "rejected" and await on_hand(client, product) == 700


async def test_branch_limit_comes_from_branch_settings(client) -> None:
    await event("branch.settings_updated", {"branch_id": str(PP1), "shrinkage_approval_usd": "5.00"})
    product, _ = await stocked()
    batch = await batch_of(client, product)
    r = await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()}, json={
        "branch_id": str(PP1), "batch_id": batch, "qty_base": 60, "reason": "broken"})  # 6 USD > 5
    assert r.json()["status"] == "pending_approval"


async def test_controlled_shrinkage_needs_pin_witness_and_method(client, auth) -> None:
    product, _ = await stocked("DIAZ5", controlled="IV")
    batch = await batch_of(client, product)
    actor = PHARMACIST["X-User-Id"]
    body = {"branch_id": str(PP1), "batch_id": batch, "qty_base": 5, "reason": "damaged"}
    r = await client.post(f"{PREFIX}/shrinkages", json=body, headers={**PHARMACIST, **idem()})
    assert r.status_code == 422 and r.json()["details"]["field"] == "destruction_method"
    body["destruction_method"] = "Crushed and mixed with cat litter"
    r = await client.post(f"{PREFIX}/shrinkages", json=body, headers={**PHARMACIST, **idem()})
    assert r.status_code == 401 and r.json()["code"] == "PIN_REQUIRED"
    pin = auth.issue(actor, "inventory.shrinkage", branches=(PP1,))
    r = await client.post(f"{PREFIX}/shrinkages", json={**body, "pin_token": pin}, headers={**PHARMACIST, **idem()})
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_REQUIRED"
    pin = auth.issue(actor, "inventory.shrinkage", branches=(PP1,))
    self_witness = auth.issue(actor, "inventory.shrinkage", "witness", branches=(PP1,))
    r = await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()},
                          json={**body, "pin_token": pin, "witness_token": self_witness})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"
    witness = str(uuid4())
    pin = auth.issue(actor, "inventory.shrinkage", branches=(PP1,))
    pin = auth.issue(actor, "inventory.shrinkage", branches=(PP1,))
    pharmacist_witness = auth.issue(witness, "inventory.shrinkage", "witness", branches=(PP1,))
    r = await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()},
                          json={**body, "pin_token": pin, "witness_token": pharmacist_witness})  # fmt: skip
    assert r.status_code == 422 and r.json()["code"] == "WITNESS_INVALID"  # destruction: manager or owner
    pin = auth.issue(actor, "inventory.shrinkage", branches=(PP1,))
    ok = auth.issue(witness, "inventory.shrinkage", "witness", branches=(PP1,), name="Witness Sok",
                    role="branch_manager")
    r = await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()},
                          json={**body, "pin_token": pin, "witness_token": ok})  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["witness_name"] == "Witness Sok" and r.json()["status"] == "posted"
    meta = [p for t, p in await outbox() if t == "stock.changed"][-1]["meta"]
    assert meta["witness_id"] == witness and meta["entry_type"] == "destroy"
    assert meta["destruction_method"].startswith("Crushed")


async def test_controlled_loss_may_have_a_pharmacist_witness(client, auth) -> None:
    product, _ = await stocked("DIAZ5", controlled="IV")
    batch = await batch_of(client, product)
    actor = PHARMACIST["X-User-Id"]
    r = await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()}, json={
        "branch_id": str(PP1), "batch_id": batch, "qty_base": 1, "reason": "lost_theft", "note": "missing at count",
        "destruction_method": "n/a (lost)", "pin_token": auth.issue(actor, "inventory.shrinkage", branches=(PP1,)),
        "witness_token": auth.issue(str(uuid4()), "inventory.shrinkage", "witness", branches=(PP1,))})  # fmt: skip
    assert r.status_code == 201, r.text


@pytest.mark.skipif(not S3_ENDPOINT, reason="TEST_S3_ENDPOINT not set")
async def test_shrinkage_photo_is_private_and_logged(client) -> None:
    await get_storage().ensure_bucket()
    product, _ = await stocked()
    batch = await batch_of(client, product)
    s = (await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()}, json={
        "branch_id": str(PP1), "batch_id": batch, "qty_base": 1, "reason": "broken"})).json()  # fmt: skip
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    r = await client.post(f"{PREFIX}/shrinkages/{s['id']}/photo", files={"file": ("x.png", buf.getvalue())},
                          headers=PHARMACIST)  # fmt: skip
    assert r.status_code == 200 and r.json()["has_photo"]
    r = await client.get(f"{PREFIX}/shrinkages/{s['id']}/photo", headers=PHARMACIST)
    assert r.content.startswith(b"\x89PNG") and r.headers["cache-control"] == "no-store"
    assert (await client.get(f"{PREFIX}/shrinkages/{s['id']}/photo", headers=CASHIER)).status_code == 403
    other_branch = user("pharmacist", "inventory.shrinkage", (PP2,))
    assert (await client.get(f"{PREFIX}/shrinkages/{s['id']}/photo", headers=other_branch)).status_code == 404


# ---------------------------------------------------------------- stock take + controlled internals


async def test_snapshot_scopes_and_changes_since(client) -> None:
    cat = str(uuid4())
    para, _ = await stocked("PARA500", category=cat)
    ors, _ = await stocked("ORS", qty=40)
    diaz, _ = await stocked("DIAZ5", qty=20, controlled="IV")
    await client.put(f"{PREFIX}/shelf-locations", headers=MANAGER,
                     json={"branch_id": str(PP1), "medicine_id": ors["id"], "code": "B1"})  # fmt: skip

    async def snap(**body) -> dict:  # noqa: ANN003
        r = await client.post("/internal/v1/stock/snapshot", json={"branch_id": str(PP1), **body}, headers=INTERNAL)
        assert r.status_code == 200, r.text
        return r.json()

    full = await snap()
    assert {x["sku"] for x in full["lines"]} == {"PARA500", "ORS", "DIAZ5"} and full["as_of_seq"] > 0
    assert [x["sku"] for x in (await snap(scope="category", category_id=cat))["lines"]] == ["PARA500"]
    assert [x["sku"] for x in (await snap(scope="location", location="b1"))["lines"]] == ["ORS"]
    assert [x["sku"] for x in (await snap(scope="controlled"))["lines"]] == ["DIAZ5"]
    batch = next(x["batch_id"] for x in full["lines"] if x["sku"] == "PARA500")
    await client.post(f"{PREFIX}/shrinkages", headers={**PHARMACIST, **idem()}, json={
        "branch_id": str(PP1), "batch_id": batch, "qty_base": 7, "reason": "damaged"})  # fmt: skip
    since = await client.post("/internal/v1/movements/since", headers=INTERNAL,
                              json={"branch_id": str(PP1), "after_seq": full["as_of_seq"]})  # fmt: skip
    assert since.json()["changes"] == {batch: -7}
    controlled = await client.post("/internal/v1/stock/controlled", json={"branch_id": str(PP1)}, headers=INTERNAL)
    assert [(x["lot_no"], x["qty_on_hand"]) for x in controlled.json()["items"]] == [("L1", 20)]
    assert diaz


async def test_count_adjustments_are_booked_once(client) -> None:
    product, _ = await stocked()
    batch = await batch_of(client, product)
    payload = {"count_id": str(uuid4()), "number": "PP1-SC-2026-000001", "branch_id": str(PP1),
               "approved_by": str(uuid4()),
               "adjustments": [{"count_line_id": str(uuid4()), "batch_id": batch, "qty_base": -4,
                                "counted_by": ["a", "b"]}]}  # fmt: skip
    await event("count.approved", payload)
    await event("count.approved", payload)  # delivered twice (new message id)
    assert await on_hand(client, product) == 96
    changed = [p for t, p in await outbox() if t == "stock.changed"][-1]
    assert changed["type"] == "count_adjust" and changed["meta"]["number"] == "PP1-SC-2026-000001"


async def test_controlled_adjust_once_per_request(client) -> None:
    product, _ = await stocked("DIAZ5", qty=20, controlled="IV")
    batch = await batch_of(client, product)
    body = {"request_id": str(uuid4()), "branch_id": str(PP1), "batch_id": batch, "kind": "destroy",
            "qty_base": 3, "reason": "expired, destroyed", "meta": {"witness_id": str(uuid4())}}  # fmt: skip
    for _ in range(2):
        r = await client.post("/internal/v1/movements/controlled", json=body, headers=INTERNAL)
        assert r.status_code == 200 and r.json()["qty_after"] == 17
    plain, _ = await stocked("ORS")
    other = await client.post("/internal/v1/movements/controlled", headers=INTERNAL,
                              json={**body, "request_id": str(uuid4()), "batch_id": await batch_of(client, plain)})  # fmt: skip
    assert other.status_code == 404
