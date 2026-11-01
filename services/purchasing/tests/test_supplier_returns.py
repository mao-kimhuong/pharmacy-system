"""Supplier returns: draft → submit (stock out through inventory, a credit on the
supplier's account applied to the oldest open bills; what is left pays the next
bill) or a refund received (owner/manager); cancel only a draft; controlled lines
need a PIN; a recall makes the draft once; cost hidden without permission."""

from decimal import Decimal
from uuid import UUID, uuid4

from purchasing_service.main import app
from purchasing_service.services.clients import get_auth, get_inventory

from .conftest import OWNER, PP1, PREFIX, SERVICE_TOKEN, add_product, idem, outbox, user
from .test_payments import balance, two_bills

RETURNER = user("pharmacist", "purchasing.return")
MANAGER_R = user("branch_manager", "purchasing.return,purchasing.pay")


class Inventory:
    """Stands in for inventory /internal/v1/movements/supplier-return (0.0425 a tablet)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, path: str, body: dict, **kw) -> dict:  # noqa: ANN003
        assert path == "/movements/supplier-return"
        self.calls.append(body)
        return {"lines": [{"line_no": x["line_no"], "batch_id": x["batch_id"], "lot_no": "A1",
                           "expiry_date": "2028-03-31", "cost_per_base": "0.0425", "qty_base": x["qty_base"]}
                          for x in body["lines"]]}  # fmt: skip


class Auth:
    """auth /pin-tokens/consume: the caller's own PIN, or another person as the witness."""

    async def post(self, path: str, body: dict, actor=None, **kw) -> dict:  # noqa: ANN001, ANN003
        own = body["kind"] != "witness"
        return {"user_id": str(actor.id if own else uuid4()), "name": "Me" if own else "Witness",
                "role": actor.role if own else "branch_manager", "is_pharmacist": True, "branch_ids": [str(PP1)],
                "permissions": ["controlled.witness"]}  # fmt: skip


def fakes() -> Inventory:
    inv = Inventory()
    app.dependency_overrides[get_inventory] = lambda: inv
    app.dependency_overrides[get_auth] = lambda: Auth()
    return inv


async def draft(client, supplier: dict, product: dict, qty: int = 200, who: dict = RETURNER) -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/supplier-returns", headers=who, json={
        "branch_id": str(PP1), "supplier_id": supplier["id"], "reason": "damaged",
        "lines": [{"batch_id": str(uuid4()), "medicine_id": product["id"], "qty_base": qty}]})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


async def submit(client, r: dict, who: dict = RETURNER, **body):  # noqa: ANN001, ANN003, ANN201
    return await client.post(f"{PREFIX}/supplier-returns/{r['id']}/submit", json=body, headers={**who, **idem()})


async def test_credit_goes_to_the_oldest_bills_and_the_rest_to_the_next_bill(client) -> None:
    inv = fakes()
    try:
        s, bills = await two_bills(client)  # 42.50 then 21.25
        para = {"id": bills[0]["lines"][0]["medicine_id"]}
        ret = await draft(client, s, para, qty=1600)  # 1600 × 0.0425 = 68.00 > 63.75 owed
        assert ret["number"] == "PP1-SRN-2026-000001" and "total" not in ret  # a pharmacist sees no cost
        r = await submit(client, ret)
        assert r.status_code == 200 and r.json()["status"] == "credited", r.text
        assert inv.calls[0]["lines"][0]["qty_base"] == 1600
        assert (await balance(client, s))["owed"] == "0.00"
        credit = [p for t, p in await outbox() if t == "supplier_credit.updated"][-1]
        assert (credit["amount"], credit["remaining"]) == ("68.00", "4.25")
        st = (await client.get(f"{PREFIX}/suppliers/{s['id']}/statement", headers=OWNER)).json()
        assert [e["kind"] for e in st["entries"]] == ["receipt", "receipt", "return"] and st["closing_balance"] == "-4.25"
        # the next bill is paid first by what is left of the credit
        from .conftest import create_po, receive

        po = await create_po(client, s, [(await add_product("ORS"), "box", 1, "10.00")], send=True)
        await receive(client, po, [{"po_line_id": po["lines"][0]["id"], "lot_no": "O1", "expiry_date": "2028-03-31",
                                    "qty": 1}])  # fmt: skip
        assert (await balance(client, s))["owed"] == "5.75"
        again = await submit(client, ret)
        assert again.status_code == 409 and again.json()["code"] == "SUPPLIER_RETURN_STATE"
    finally:
        app.dependency_overrides.clear()


async def test_refund_only_by_owner_or_manager_and_cancel_only_a_draft(client) -> None:
    fakes()
    try:
        s, bills = await two_bills(client)
        para = {"id": bills[0]["lines"][0]["medicine_id"]}
        ret = await draft(client, s, para, qty=100)
        r = await submit(client, ret, settle="refund", refund_method="cash")
        assert r.status_code == 403
        r = await submit(client, ret, MANAGER_R, settle="refund", refund_method="ABA", refund_reference="TX-9")
        assert r.status_code == 200 and r.json()["status"] == "refunded" and r.json()["total"] == "4.25", r.text
        assert (await balance(client, s))["owed"] == "63.75"  # the bills are untouched: the money came back
        refund = [p for t, p in await outbox() if t == "supplier_refund.created"][-1]
        assert refund["number"] == "PP1-SRF-2026-000001" and refund["amount"] == "4.25"
        r = await client.post(f"{PREFIX}/supplier-returns/{ret['id']}/cancel", json={"reason": "x"}, headers=RETURNER)
        assert r.status_code == 409
        other = await draft(client, s, para, qty=10)
        r = await client.post(f"{PREFIX}/supplier-returns/{other['id']}/cancel", json={"reason": "wrong lot"},
                              headers=RETURNER)  # fmt: skip
        assert r.json()["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()


async def test_controlled_needs_pin_and_a_recall_drafts_once(client) -> None:
    inv = fakes()
    try:
        s, _ = await two_bills(client)
        diaz = await add_product("DIAZ5", controlled="IV")
        ret = await draft(client, s, diaz, qty=10)
        app.dependency_overrides.pop(get_auth)
        r = await submit(client, ret)
        assert r.status_code == 401 and r.json()["code"] == "PIN_REQUIRED"
        app.dependency_overrides[get_auth] = lambda: Auth()
        r = await submit(client, ret, pin_token="p", witness_token="w")
        assert r.status_code == 200, r.text
        assert inv.calls[-1]["lines"][0]["meta"]["entry_type"] == "supplier_return"
        body = {"branch_id": str(PP1), "supplier_id": s["id"], "reason": "recalled", "source_ref": "recall_line:1",
                "lines": [{"batch_id": str(uuid4()), "medicine_id": diaz["id"], "qty_base": 5}]}  # fmt: skip
        headers = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "inventory"}
        a = await client.post("/internal/v1/supplier-returns/from-recall", json=body, headers=headers)
        b = await client.post("/internal/v1/supplier-returns/from-recall", json=body, headers=headers)
        assert a.status_code == 200 and a.json()["id"] == b.json()["id"]
        assert UUID(a.json()["id"]) and Decimal("1")
    finally:
        app.dependency_overrides.clear()
