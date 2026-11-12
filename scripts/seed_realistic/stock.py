"""Stock: purchase orders → receiving (two lots per line), SR1's opening stock by Initialize, supplier payments.
Quantities come from the sales plan (what each branch will sell), so FEFO always has stock and leftovers stay."""

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from client import Api, ApiError, Person, key
from data import SUPPLIERS
from setup import money

COST_SHARE = Decimal("0.62")  # buying price ≈ 62 % of the selling price


def buy_pack(med: dict) -> dict:
    """The biggest pack (what a pharmacy orders), else the base unit."""
    return max(med["packs"].values(), key=lambda p: p["qty_in_base"])


def supplier_for(sku: str, rng_index: int) -> str:
    return SUPPLIERS[(sum(map(ord, sku)) + rng_index) % len(SUPPLIERS)][0]


def lots(sku: str, branch: str, wave: int, real_today: date, special: dict) -> list[tuple[str, date, float]]:
    """(lot, expiry, share of the qty). Mostly 1–3 years out; chosen lines expire soon or already did."""
    h = sum(map(ord, sku + branch)) + wave * 31
    far = real_today + timedelta(days=365 + h % 730)
    near = real_today + timedelta(days=400 + (h * 7) % 600)
    if (sku, branch, wave) in special:
        return special[(sku, branch, wave)]
    return [(f"{sku[:4]}{branch}{wave}A{h % 97:02d}", near, 0.5), (f"{sku[:4]}{branch}{wave}B{h % 89:02d}", far, 0.5)]


def special_lots(real_today: date, days_n: int = 90) -> dict:
    """A few lots that tell a story in the expiry reports. The two expired ones expire inside the seeded window
    (received fine, sold FEFO first, then expired on the shelf)."""
    t = real_today
    e1, e2 = min(12, max(1, days_n // 4)), min(25, max(1, days_n // 3))
    return {
        ("VITC500", "PP1", 1): [("VITC-EXP1", t - timedelta(days=e1), 0.3), ("VITC-PP1-B", t + timedelta(days=600), 0.7)],
        ("DECOL", "PP2", 1): [("DECO-EXP2", t - timedelta(days=e2), 0.3), ("DECO-PP2-B", t + timedelta(days=500), 0.7)],
        ("AMBRO30", "PP1", 2): [("AMBR-30D", t + timedelta(days=21), 0.4), ("AMBR-PP1-C", t + timedelta(days=700), 0.6)],
        ("CETI10", "PP2", 2): [("CETI-90D", t + timedelta(days=75), 0.4), ("CETI-RECALL", t + timedelta(days=640), 0.6)],
        ("LOPE2", "SR1", 2): [("LOPE-30D", t + timedelta(days=28), 0.5), ("LOPE-SR1-C", t + timedelta(days=560), 0.5)],
        ("OMEP20", "PP1", 2): [("OMEP-90D", t + timedelta(days=84), 0.5), ("OMEP-PP1-C", t + timedelta(days=720), 0.5)],
    }


async def receive_po(api: Api, buyer: Person, receiver: Person, branch: str, branch_id: str, supplier: dict,
                     lines: list[tuple[str, int]], meds: dict, at: datetime, wave: int, real_today: date,
                     special: dict) -> dict | None:  # fmt: skip
    """One PO: draft → sent → received (two lots per line). Replays on a second run (same keys)."""
    body = {"branch_id": branch_id, "supplier_id": supplier["id"], "note": f"Stock wave {wave}", "lines": [
        {"medicine_id": meds[s]["id"], "pack_unit_id": buy_pack(meds[s])["id"], "qty": q,
         "unit_cost": money(Decimal(buy_pack(meds[s])["sell_price"]) * COST_SHARE)} for s, q in lines]}  # fmt: skip
    po = await api.post("purchasing", "/purchase-orders", buyer, body, at=at)
    po = await api.post("purchasing", f"/purchase-orders/{po['id']}/send", buyer, at=at)
    rec_lines = []
    for pl, (sku, q) in zip(po["lines"], lines, strict=True):
        parts = lots(sku, branch, wave, real_today, special)
        left = q
        for i, (lot, exp, share) in enumerate(parts):
            n = left if i == len(parts) - 1 else max(1, round(q * share))
            n = min(n, left)
            left -= n
            if n > 0:
                rec_lines.append({"po_line_id": pl["id"], "lot_no": lot, "expiry_date": exp.isoformat(), "qty": n})
    return await api.post("purchasing", f"/purchase-orders/{po['id']}/receive", receiver,
                          {"lines": rec_lines, "supplier_invoice_no": f"{supplier['code']}-{branch}-{wave}-{po['number'][-4:]}"},
                          at=at + timedelta(hours=2), key=key("receive", po["id"]))  # fmt: skip


def packs_needed(demand_base: int, pack: dict) -> int:
    return max(2, math.ceil(demand_base * 1.6 / pack["qty_in_base"]))  # safety stock: no empty shelf mid-period


async def stock_wave(api: Api, who: dict[str, Person], branch_ids: dict[str, str], suppliers: dict, meds: dict,
                     demand: dict[tuple[str, str], int], wave: int, at: datetime, real_today: date,
                     state: dict, branches: list[str]) -> None:  # fmt: skip
    special = special_lots(real_today, state.get("days_n", 90))
    for branch in branches:
        done_key = f"wave{wave}:{branch}"
        if done_key in state.setdefault("done", []):
            continue
        by_supplier: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for (b, sku), need in sorted(demand.items()):
            if b != branch or meds[sku]["hamper"] or need <= 0:
                continue
            by_supplier[supplier_for(sku, 0)].append((sku, packs_needed(need, buy_pack(meds[sku]))))
        for code, lines in sorted(by_supplier.items()):
            one = f"{done_key}:{code}"  # per PO: a run that stopped half-way does not order twice
            if one in state["done"]:
                continue
            await receive_po(api, who[f"{branch}.branch_manager1"], who[f"{branch}.pharmacist1"], branch,
                             branch_ids[branch], suppliers[code], lines, meds, at, wave, real_today, special)  # fmt: skip
            state["done"].append(one)
        expect = len({s for ls in by_supplier.values() for s, _ in ls})
        await wait_for_stock(api, who[f"{branch}.branch_manager1"], branch_ids[branch], expect)
        state["done"].append(done_key)


async def wait_for_stock(api: Api, who: Person, branch_id: str, expect: int, tries: int = 120) -> int:
    """goods.received reaches inventory as an event a moment later: wait until the branch shows the stock."""
    import asyncio

    have = 0
    for _ in range(tries):
        page = await api.get("inventory", "/stock", who, params={"branch_id": branch_id, "size": 1})
        have = page.get("total", 0)
        if have >= expect:
            return have
        await asyncio.sleep(1)
    return have


async def initialize(api: Api, manager: Person, owner: Person, branch: str, branch_id: str, meds: dict,
                     demand: dict, at: datetime, real_today: date, state: dict) -> None:  # fmt: skip
    """SR1 starts with opening stock (Initialize: validate → commit; the branch is then locked)."""
    if f"init:{branch}" in state.setdefault("done", []):
        return
    special = special_lots(real_today, state.get("days_n", 90))
    lines = []
    for (b, sku), need in sorted(demand.items()):
        if b != branch or meds[sku]["hamper"] or need <= 0:
            continue
        pack = buy_pack(meds[sku])
        q = packs_needed(need, pack)
        for i, (lot, exp, share) in enumerate(lots(sku, branch, 1, real_today, special)):
            n = q - sum(x["qty"] for x in lines if x["medicine_id"] == meds[sku]["id"]) if i else max(1, round(q * share))
            if n > 0:
                lines.append({"medicine_id": meds[sku]["id"], "pack_unit_id": pack["id"], "lot_no": lot,
                              "expiry_date": exp.isoformat(), "qty": n,
                              "unit_cost": money(Decimal(pack["sell_price"]) * COST_SHARE)})  # fmt: skip
    try:
        opening = await api.post("inventory", "/opening-balances", owner, {"branch_id": branch_id, "lines": lines}, at=at)
        await api.post("inventory", f"/opening-balances/{opening['id']}/commit", owner, at=at, key=key("init", branch))
    except ApiError as err:
        if "LOCK" not in str(err.code or "") and err.status != 409:
            raise
    state["done"].append(f"init:{branch}")


async def pay_suppliers(api: Api, who: dict[str, Person], branch_ids: dict[str, str], suppliers: dict, at: datetime,
                        share: dict[str, float], state: dict, tag: str) -> None:  # fmt: skip
    """Pays a share of what each branch owes each supplier (oldest bills first); the rest stays for aging."""
    if f"pay:{tag}" in state.setdefault("done", []):
        return
    for branch, bid in branch_ids.items():
        for code, sup in sorted(suppliers.items()):
            bal = await api.get("purchasing", f"/suppliers/{sup['id']}/balance", who[f"{branch}.branch_manager1"])
            mine = next((x for x in bal.get("branches", []) if x["branch_id"] == bid), {"owed": "0"})
            owed = Decimal(str(mine.get("owed") or "0"))
            amount = (owed * Decimal(str(share.get(branch, 0)))).quantize(Decimal("0.01"))
            if amount > 0:
                await api.post("purchasing", "/supplier-payments", who[f"{branch}.branch_manager1"], {
                    "supplier_id": sup["id"], "branch_id": bid, "method": "bank" if amount > 200 else "ABA",
                    "amount": str(amount), "reference": f"TT-{code}-{branch}-{tag}"},
                    at=at, key=key("supplier-pay", tag, branch, code))  # fmt: skip
    state["done"].append(f"pay:{tag}")


__all__: list[Any] = ["stock_wave", "initialize", "pay_suppliers"]
