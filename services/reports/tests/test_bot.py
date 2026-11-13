"""T2 phase 3: the figures behind the Telegram bot commands (/internal/v1/bot/…) and the first / last sale."""

from uuid import uuid4

from .conftest import INTERNAL, PP1, PP2, event, invoice, line, product


async def bot(client, command: str, **params):  # noqa: ANN001, ANN003, ANN201
    return await client.get(f"/internal/v1/bot/{command}", headers=INTERNAL, params={k: str(v) for k, v in params.items()})


async def test_day_top_cash_scoped_to_branches_with_first_and_last_sale(client) -> None:
    assert (await client.get("/internal/v1/bot/day")).status_code == 401
    para, ors = await product(), await product("ORS")
    await event("invoice.created", invoice("A", [line(para, 10, "1.00", "0.40")], at="2026-10-27T00:15:00+00:00"))
    await event("invoice.created", invoice("B", [line(ors, 5, "2.50", "1.00", sku="ORS")], at="2026-10-27T12:40:00+00:00",
                                           payments=[{"method": "KHQR", "currency": "KHR", "amount": "10300",
                                                      "amount_usd": "2.50"}]))  # fmt: skip
    await event("invoice.created", invoice("C", [line(para, 10, "9.00", "4.00")], branch=PP2))
    r = (await bot(client, "day", day="2026-10-27", branch_ids=str(PP1))).json()
    assert [b["code"] for b in r["branches"]] == ["PP1"] and "gross_profit" not in r["figures"]
    assert (r["figures"]["net_sales"], r["figures"]["invoices"]) == ("3.50", 2)
    assert (r["first_sale"], r["last_sale"]) == ("07:15", "19:40")  # Phnom Penh time
    every = (await bot(client, "day", day="2026-10-27", profit="true")).json()
    assert every["figures"]["net_sales"] == "12.50" and every["figures"]["gross_profit"] == "7.10"
    top = (await bot(client, "top", day="2026-10-27", branch_ids=str(PP1), n=10)).json()["items"]
    assert [x["sku"] for x in top] == ["ORS", "PARA500"]
    cash = (await bot(client, "cash", day="2026-10-27", branch_ids=str(PP1))).json()
    assert {(x["method"], x["currency"]) for x in cash["items"]} == {("cash", "USD"), ("KHQR", "KHR")}
    assert cash["total_usd"] == "3.50"
    summary = (await client.get("/internal/v1/daily-summary", headers=INTERNAL, params={"branch_id": str(PP1)})).json()
    assert (summary["first_sale"], summary["last_sale"]) == ("07:15", "19:40")


async def test_stock_by_name_or_barcode_and_debtors_without_names(client) -> None:
    para = await product()
    batch = uuid4()
    for branch, qty in ((PP1, 120), (PP2, 40)):
        await event("stock.changed", {"movement_id": str(uuid4()), "seq": qty, "branch_id": str(branch),
                                      "batch_id": str(batch), "medicine_id": str(para), "type": "in", "delta": qty,
                                      "qty_after": qty, "lot_no": "L1", "expiry_date": "2027-06-30",
                                      "cost_per_base": "0.0500", "occurred_at": "2026-06-01T03:00:00+00:00"})  # fmt: skip
    r = (await bot(client, "stock", q="para")).json()["items"]
    assert [(x["sku"], x["on_hand"], x["total"]) for x in r] == [("PARA500", {"PP1": 120, "PP2": 40}, 160)]
    mine = (await bot(client, "stock", q="PARA500", branch_ids=str(PP1))).json()["items"]
    assert mine[0]["on_hand"] == {"PP1": 120}
    assert (await bot(client, "stock", q="nothing-like-this")).json() == {"items": []}
    assert (await bot(client, "debtors", names="false")).json() == {"items": []}
    assert (await bot(client, "nope")).status_code == 404
