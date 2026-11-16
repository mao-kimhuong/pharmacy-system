"""Stock takes: blind counting, double counts, sales during a count, approval
limits, PIN for controlled variances, adjustments posted once."""

from .conftest import (
    APPROVER,
    AUTH,
    COUNTER_A,
    COUNTER_B,
    OWNER,
    PP1,
    PP2,
    PREFIX,
    add_product,
    event,
    on_hand,
    outbox,
    receive,
    relay_approved,
    sell_now,
    user,
)  # fmt: skip


async def start(client, scope: str = "full", headers=APPROVER, **extra) -> dict:  # noqa: ANN001
    r = await client.post(f"{PREFIX}/counts", json={"branch_id": str(PP1), "scope": scope, **extra}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def count_line(client, count: dict, sku: str, qty: int, headers=COUNTER_A):  # noqa: ANN001, ANN201
    line = next(x for x in count["lines"] if x["sku"] == sku)
    r = await client.post(f"{PREFIX}/counts/{count['id']}/entries", json={"line_id": line["id"], "qty": qty},
                          headers=headers)  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


async def test_counters_never_see_expected_quantities(client) -> None:
    para = await add_product("PARA500", barcode="8841000100017")
    await receive(para, 100)
    count = await start(client)
    assert count["number"] == "PP1-SC-2026-000001"
    line = count["lines"][0]
    for hidden in ("snapshot_qty", "expected_qty", "counted_qty", "variance", "cost_per_base"):
        assert hidden not in line
    view = (await client.get(f"{PREFIX}/counts/{count['id']}", headers=COUNTER_A)).json()
    assert "snapshot_qty" not in view["lines"][0]
    found = (await client.get(f"{PREFIX}/counts/{count['id']}/lookup", params={"barcode": "8841000100017"},
                              headers=COUNTER_A)).json()  # fmt: skip
    assert [(x["sku"], x["lot_no"]) for x in found] == [("PARA500", "L1")] and "snapshot_qty" not in found[0]
    assert (await client.get(f"{PREFIX}/counts/{count['id']}/review", headers=COUNTER_A)).status_code == 403


async def test_controlled_and_valuable_lines_need_two_people_who_agree(client) -> None:
    diaz = await add_product("DIAZ5", controlled="IV")
    await receive(diaz, 20)
    gold = await add_product("GOLD", None)
    await receive(gold, 10, cost="9.0000")  # 90 USD > 50: count twice
    cheap = await add_product("ORS")
    await receive(cheap, 10)
    count = await start(client)
    needs = {x["sku"]: x["needs_double"] for x in count["lines"]}
    assert needs == {"DIAZ5": True, "GOLD": True, "ORS": False}
    assert (await count_line(client, count, "ORS", 10))["status"] == "agreed"
    assert (await count_line(client, count, "DIAZ5", 20))["status"] == "needs_second"
    assert (await count_line(client, count, "DIAZ5", 20))["status"] == "needs_second"  # same person again
    assert (await count_line(client, count, "DIAZ5", 19, COUNTER_B))["status"] == "recount"
    assert (await count_line(client, count, "DIAZ5", 20, COUNTER_B))["status"] == "agreed"  # B corrects own count
    r = await client.post(f"{PREFIX}/counts/{count['id']}/submit", headers=APPROVER)
    assert r.status_code == 409 and r.json()["details"]["lines"][0]["sku"] == "GOLD"


async def test_sales_during_the_count_are_not_a_variance(client) -> None:
    para = await add_product("PARA500")
    await receive(para, 30)
    count = await start(client)
    await sell_now(para, 5)  # sold before the shelf was counted: 25 left on the shelf
    await count_line(client, count, "PARA500", 25)
    await sell_now(para, 3)  # sold after counting: not part of this line's expected figure
    r = await client.post(f"{PREFIX}/counts/{count['id']}/submit", headers=APPROVER)
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert (line["snapshot_qty"], line["expected_qty"], line["counted_qty"], line["variance"]) == (30, 25, 25, 0)


async def test_approve_posts_variances_once_and_cost_is_hidden(client) -> None:
    para = await add_product("PARA500")
    await receive(para, 100)
    count = await start(client)
    await count_line(client, count, "PARA500", 96)
    review = (await client.post(f"{PREFIX}/counts/{count['id']}/submit", headers=APPROVER)).json()
    assert review["lines"][0]["variance"] == -4 and "variance_value" not in review["lines"][0]
    rich = (await client.get(f"{PREFIX}/counts/{count['id']}/review",
                             headers=user("pharmacist", "stockcount.approve,finance.cost_profit"))).json()  # fmt: skip
    assert rich["lines"][0]["variance_value"] == "-0.20" and rich["variance_value"] == "0.20"
    r = await client.post(f"{PREFIX}/counts/{count['id']}/approve", json={},
                          headers={**APPROVER, "Idempotency-Key": "approve-0001"})  # fmt: skip
    assert r.status_code == 200 and r.json()["status"] == "approved"
    sent = {t: p for t, p in await outbox()}
    assert sent["count.submitted"]["lines"][0]["variance"] == -4 and sent["count.submitted"]["variance_value"] == "0.20"
    assert sent["count.approved"]["lines"][0]["value"] == "-0.20"  # reports: stock take variances
    await relay_approved()
    await relay_approved()
    assert await on_hand(para) == 96
    again = await client.post(f"{PREFIX}/counts/{count['id']}/approve", json={},
                              headers={**APPROVER, "Idempotency-Key": "approve-0002"})  # fmt: skip
    assert again.status_code == 409 and again.json()["code"] == "COUNT_STATE"


async def test_big_variance_needs_the_owner(client) -> None:
    await event("branch.settings_updated", {"branch_id": str(PP1), "double_count_above_usd": "1000",
                                            "owner_approval_above_usd": "10"})  # fmt: skip
    para = await add_product("PARA500")
    await receive(para, 100, cost="1.0000")
    count = await start(client)
    await count_line(client, count, "PARA500", 80)  # -20 USD
    await client.post(f"{PREFIX}/counts/{count['id']}/submit", headers=APPROVER)
    r = await client.post(f"{PREFIX}/counts/{count['id']}/approve", json={},
                          headers={**APPROVER, "Idempotency-Key": "approve-0003"})  # fmt: skip
    assert r.status_code == 403 and r.json()["code"] == "OWNER_APPROVAL_REQUIRED"
    r = await client.post(f"{PREFIX}/counts/{count['id']}/approve", json={},
                          headers={**OWNER, "Idempotency-Key": "approve-0004"})  # fmt: skip
    assert r.status_code == 200


async def test_controlled_variance_needs_the_approvers_pin(client) -> None:
    diaz = await add_product("DIAZ5", controlled="IV")
    await receive(diaz, 20)
    count = await start(client, "controlled")
    await count_line(client, count, "DIAZ5", 18)
    await count_line(client, count, "DIAZ5", 18, COUNTER_B)
    await client.post(f"{PREFIX}/counts/{count['id']}/submit", headers=APPROVER)
    r = await client.post(f"{PREFIX}/counts/{count['id']}/approve", json={},
                          headers={**APPROVER, "Idempotency-Key": "approve-0005"})  # fmt: skip
    assert r.status_code == 401 and r.json()["code"] == "PIN_REQUIRED"
    token = AUTH.issue(APPROVER["X-User-Id"], "stockcount.approve", branches=(PP1,))
    r = await client.post(f"{PREFIX}/counts/{count['id']}/approve", json={"pin_token": token},
                          headers={**APPROVER, "Idempotency-Key": "approve-0006"})  # fmt: skip
    assert r.status_code == 200, r.text
    await relay_approved()
    assert await on_hand(diaz) == 18


async def test_recount_cancel_one_open_and_branch_scope(client) -> None:
    para = await add_product("PARA500")
    await receive(para, 10)
    count = await start(client)
    assert (await client.post(f"{PREFIX}/counts", json={"branch_id": str(PP1)}, headers=APPROVER)).status_code == 409
    other = user("pharmacist", "stockcount.count,stockcount.approve", (PP2,))
    assert (await client.get(f"{PREFIX}/counts/{count['id']}", headers=other)).status_code == 404
    await count_line(client, count, "PARA500", 7)
    review = (await client.post(f"{PREFIX}/counts/{count['id']}/submit", headers=APPROVER)).json()
    r = await client.post(f"{PREFIX}/counts/{count['id']}/recount", headers=APPROVER,
                          json={"line_ids": [review["lines"][0]["id"]], "reason": "looks wrong"})  # fmt: skip
    assert r.json()["status"] == "counting" and r.json()["lines"][0]["status"] == "recount"
    assert len(r.json()["lines"][0]["counts"]) == 1  # the earlier count is kept
    assert (await count_line(client, count, "PARA500", 10))["status"] == "agreed"
    r = await client.post(f"{PREFIX}/counts/{count['id']}/cancel", json={"reason": "do it tomorrow"}, headers=APPROVER)
    assert r.json()["status"] == "cancelled"
    assert (await client.post(f"{PREFIX}/counts/{count['id']}/cancel", json={"reason": "x"},
                              headers=APPROVER)).status_code == 409  # fmt: skip
    await start(client)  # a new one can start now


# ---------------------------------------------------------------- T2: decided on Telegram


async def _in_review(client, sku: str, qty: int, counted: int, controlled: str | None = None) -> dict:  # noqa: ANN001
    med = await add_product(sku, controlled)
    await receive(med, qty)
    count = await start(client, "controlled" if controlled else "full")
    await count_line(client, count, sku, counted)
    if controlled:
        await count_line(client, count, sku, counted, COUNTER_B)
    r = await client.post(f"{PREFIX}/counts/{count['id']}/submit", headers=APPROVER)
    assert r.status_code == 200, r.text
    return count


def _actor(role: str = "pharmacist", perms: str = "stockcount.approve") -> dict:
    return {"user_id": APPROVER["X-User-Id"], "name": "Dara", "role": role, "branch_ids": [str(PP1)],
            "permissions": perms.split(",")}  # fmt: skip


async def test_count_approved_on_telegram_but_never_a_controlled_variance(client) -> None:
    from .conftest import SERVICE_TOKEN

    internal = {"X-Service-Token": SERVICE_TOKEN, "X-Service-Name": "notification"}
    count = await _in_review(client, "PARA500", 100, 96)
    submitted = [p for t, p in await outbox() if t == "count.submitted"][-1]
    assert (submitted["needs_owner"], submitted["needs_pin"]) == (False, False)
    url = f"/internal/v1/counts/{count['id']}/decide"
    r = await client.post(url, json={"decision": "reject", "actor": _actor()}, headers=internal)
    assert r.status_code == 422  # stock takes are sent back in the app
    r = await client.post(url, json={"decision": "approve", "actor": _actor(perms="stockcount.count")}, headers=internal)
    assert r.status_code == 403
    r = await client.post(url, json={"decision": "approve", "actor": _actor()}, headers=internal)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    approved = [p for t, p in await outbox() if t == "count.approved"][-1]
    log = [p for t, p in await outbox() if t == "audit.recorded" and p["action"] == "stock_count.approved"][-1]
    assert approved["via"] == "telegram" and log["after"]["via"] == "telegram"
    ctl = await _in_review(client, "DIAZ5", 20, 18, controlled="IV")
    assert [p for t, p in await outbox() if t == "count.submitted"][-1]["needs_pin"] is True
    r = await client.post(f"/internal/v1/counts/{ctl['id']}/decide", json={"decision": "approve", "actor": _actor()},
                          headers=internal)  # fmt: skip
    assert r.status_code == 403 and "PIN" in r.json()["message"]
