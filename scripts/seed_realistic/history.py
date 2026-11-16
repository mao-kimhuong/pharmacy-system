"""90 days of trade, each call at its own (dev clock) time: sales with cash / KHQR / credit in USD and KHR,
Rx sales (partial fills, allergy overrides), controlled dispensing with PIN, promotions, sale orders with deposits,
suspended carts, returns (some to quarantine), cancellations, transfers (one short), shrinkage (one controlled
destruction with a witness), customer payments."""

import asyncio
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

from client import Api, ApiError, Person, key
from setup import RATE

TZ_OFFSET = "+07:00"


@dataclass
class Sale:
    branch: str
    day: date
    n: int
    at: datetime
    seller: str
    lines: list[tuple[str, str, int]]  # sku, pack name, qty
    pay: str  # cash_usd | cash_khr | khqr | credit
    customer: int | None = None
    done: dict = field(default_factory=dict)


def local(day: date, hour: int, minute: int) -> datetime:
    return datetime.fromisoformat(f"{day.isoformat()}T{hour:02d}:{minute:02d}:00{TZ_OFFSET}")


def hour_weights() -> list[tuple[int, float]]:
    # opening 7:00, a morning bump, lunch, and the evening rush after work
    return [(7, 3), (8, 6), (9, 7), (10, 6), (11, 6), (12, 5), (13, 4), (14, 4), (15, 5), (16, 6), (17, 9), (18, 11),
            (19, 10), (20, 7), (21, 3)]  # fmt: skip


def sellable(meds: dict) -> tuple[list[str], list[float]]:
    skus = [s for s, m in meds.items() if m["row"] and not m["rx"] and not m["hamper"] and m["base"] and m["packs"]]
    return skus, [meds[s]["row"]["pop"] for s in skus]


def plan_sales(meds: dict, branches: list[str], sellers: dict[str, list[str]], customers: list[dict], days: list[date],
               lo: int, hi: int, rng: random.Random) -> list[Sale]:  # fmt: skip
    skus, weights = sellable(meds)
    hours, hw = zip(*hour_weights(), strict=True)
    credit_customers = [i for i, c in enumerate(customers) if c["credit"] > 0]
    hampers = [s for s, m in meds.items() if m["hamper"]]
    out = []
    for day in days:
        weekend = day.weekday() >= 5
        for branch in branches:
            size = {"PP1": 1.0, "PP2": 0.85, "SR1": 0.7}[branch]
            n = int(rng.randint(lo, hi) * size * (1.25 if weekend else 1.0))
            for i in range(n):
                h = rng.choices(hours, hw)[0]
                lines = []
                for sku in {rng.choices(skus, weights)[0] for _ in range(rng.choices((1, 2, 3, 4), (45, 32, 16, 7))[0])}:
                    packs = meds[sku]["packs"]
                    small = [p for p in packs.values() if not p["is_base"] and p["qty_in_base"] <= 30]
                    if small and rng.random() < 0.75:
                        pack = min(small, key=lambda p: p["qty_in_base"])["name"]
                    elif len(packs) > 1 and rng.random() < 0.08:
                        pack = max(packs.values(), key=lambda p: p["qty_in_base"])["name"]
                    else:
                        pack = next(p for p in packs.values() if p["is_base"])["name"]
                    qty = rng.choices((1, 2, 3), (70, 22, 8))[0]
                    if meds[sku]["packs"][pack]["is_base"] and meds[sku]["packs"][pack]["qty_in_base"] == 1 and \
                            meds[sku]["row"]["base"] in ("tablet", "capsule", "sachet", "piece", "lozenge"):  # fmt: skip
                        qty = rng.choice((2, 4, 6, 10))
                    lines.append((sku, pack, qty))
                if hampers and rng.random() < 0.01:
                    kit = rng.choice(hampers)
                    lines.append((kit, meds[kit]["base"]["name"], 1))
                r = rng.random()
                pay = "cash_usd" if r < 0.55 else "cash_khr" if r < 0.73 else "khqr" if r < 0.90 else "credit"
                customer = rng.choice(credit_customers) if pay == "credit" and credit_customers else None
                if pay == "credit" and customer is None:
                    pay = "cash_usd"
                out.append(Sale(branch, day, i, local(day, h, rng.randint(0, 59)), rng.choice(sellers[branch]), lines,
                                pay, customer))  # fmt: skip
    out.sort(key=lambda s: s.at)
    return out


def demand(plan: list[Sale], meds: dict, extra: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    """Base units each branch will sell of each medicine (hampers as their components)."""
    need: dict[tuple[str, str], int] = defaultdict(int)
    for s in plan:
        for sku, pack, qty in s.lines:
            m = meds[sku]
            if m["hamper"]:
                for c_sku, c_qty in m.get("components", []):
                    need[(s.branch, c_sku)] += c_qty * qty
                continue
            need[(s.branch, sku)] += m["packs"][pack]["qty_in_base"] * qty
    for k, v in extra.items():
        need[k] += v
    return need


def list_total(meds: dict, lines: list[tuple[str, str, int]]) -> Decimal:
    total = Decimal("0")
    for sku, pack, qty in lines:
        total += Decimal(meds[sku]["packs"][pack]["sell_price"]) * qty
    return total


def body_lines(meds: dict, lines: list[tuple[str, str, int]]) -> list[dict]:
    return [{"medicine_id": meds[sku]["id"], "pack_unit_id": meds[sku]["packs"][pack]["id"], "qty": qty}
            for sku, pack, qty in lines]


class Trade:
    def __init__(self, api: Api, who: dict[str, Person], branch_ids: dict[str, str], meds: dict, customers: list[dict],
                 patients: list[dict], doctors: list[dict], rng: random.Random, state: dict) -> None:  # fmt: skip
        self.api, self.who, self.branch_ids, self.meds = api, who, branch_ids, meds
        self.customers, self.patients, self.doctors, self.rng, self.state = customers, patients, doctors, rng, state
        self.invoices: dict[str, list[dict]] = defaultdict(list)  # per branch, completed (id, lines, at)
        self.owed: dict[tuple[str, int], Decimal] = defaultdict(Decimal)  # (branch, customer): credit not paid yet
        self.count = defaultdict(int)
        self.failed: list[str] = []

    # ---------------------------------------------------------------- one sale

    async def sell(self, s: Sale) -> None:
        seller = self.who[s.seller]
        bid = self.branch_ids[s.branch]
        body: dict[str, Any] = {"branch_id": bid, "lines": body_lines(self.meds, s.lines)}
        k = key("inv", s.branch, s.day, s.n)
        try:
            if s.pay in ("khqr", "credit"):
                customer = self.customers[s.customer] if s.customer is not None else None
                if customer:
                    body["customer_id"] = customer["id"]
                preview = await self.api.post("sales", "/carts/preview", seller, body, at=s.at)
                total = Decimal(preview["total"])
                if not preview.get("can_post") or total <= 0:
                    s.pay = "cash_usd"
                elif s.pay == "khqr":
                    qr = await self.api.post("sales", "/payments/khqr", seller, {"branch_id": bid, "amount": str(total),
                                             "currency": "USD"}, at=s.at, key=key("qr", k))  # fmt: skip
                    await self.api.post("sales", f"/khqr/fake/{qr['id']}/pay", None, internal=True, ok=(204,))
                    body["payments"] = [{"method": "KHQR", "currency": "USD", "amount": str(total), "khqr_id": qr["id"]}]
                else:
                    owed = sum(v for (b, c), v in self.owed.items() if c == s.customer)
                    if customer is None or customer["credit"] - owed < total:
                        s.pay = "cash_usd"
                    else:
                        body["payments"] = [{"method": "credit", "currency": "USD", "amount": str(total)}]
            if s.pay == "cash_usd":
                body["payments"] = [{"method": "cash", "currency": "USD",
                                     "amount": str(math.ceil(list_total(self.meds, s.lines)))}]  # fmt: skip
            elif s.pay == "cash_khr":
                riel = (list_total(self.meds, s.lines) * RATE / 1000).to_integral_value(ROUND_CEILING) * 1000
                body["payments"] = [{"method": "cash", "currency": "KHR", "amount": str(riel)}]
                body["change_in"] = "KHR"
            inv = await self._post_sale(s, seller, body, k)
            if inv.get("status") == "completed":
                self.invoices[s.branch].append({"id": inv["id"], "lines": inv["lines"], "at": s.at, "day": s.day,
                                                "pay": s.pay})  # fmt: skip
                self.count["sales"] += 1
            else:
                self.count["sale_" + str(inv.get("status"))] += 1
        except ApiError as err:
            self.count[f"refused:{err.code}"] += 1
            if len(self.failed) < 20:
                self.failed.append(f"{s.branch} {s.at:%Y-%m-%d %H:%M} {err}")

    async def _post_sale(self, s: Sale, seller: Person, body: dict, k: str) -> dict:
        """The sale; a QR the (real-time) poller expired in the instant before it was paid gets a new one."""
        for attempt in range(3):
            try:
                inv = await self.api.post("sales", "/invoices", seller, body, at=s.at, key=k if not attempt else key(k, attempt))
                if body["payments"][0]["method"] == "credit" and inv.get("status") == "completed":
                    self.owed[(s.branch, s.customer)] += Decimal(body["payments"][0]["amount"])
                return inv
            except ApiError as err:
                pay = body["payments"][0]
                if err.code == "KHQR_NOT_PAID" and attempt < 2:
                    qr = await self.api.post("sales", "/payments/khqr", seller, {"branch_id": body["branch_id"],
                                             "amount": pay["amount"], "currency": "USD"}, at=s.at, key=key("qr", k, attempt))  # fmt: skip
                    await self.api.post("sales", f"/khqr/fake/{qr['id']}/pay", None, internal=True, ok=(204,))
                    pay["khqr_id"] = qr["id"]
                    self.count["khqr_expired_retried"] += 1
                    continue
                if err.code == "CREDIT_LIMIT_EXCEEDED" and attempt < 2:
                    body.pop("customer_id", None)
                    body["payments"] = [{"method": "cash", "currency": "USD", "amount": str(math.ceil(Decimal(pay["amount"])))}]
                    continue
                raise
        raise ApiError(0, {"code": "GAVE_UP"}, "sale")

    async def run_day(self, sales: list[Sale]) -> None:
        await asyncio.gather(*(self.sell(s) for s in sales))

    # ---------------------------------------------------------------- prescriptions

    async def rx_sale(self, branch: str, day: date, n: int, at: datetime) -> None:
        """A pharmacist fills part of a prescription; a patient allergic to the drug gets it with an override."""
        rng = self.rng
        pharm = self.who[f"{branch}.pharmacist{1 + n % 2}"]
        mine = [p for p in self.patients if p["branch"] == branch]
        patient = mine[(day.toordinal() * 3 + n) % len(mine)]
        doctor = self.doctors[(day.toordinal() + n) % len(self.doctors)]
        allergic = any(a["value"] == "penicillins" for a in patient["allergies"])
        sku = "AMOX500" if allergic and rng.random() < 0.5 else rng.choice(
            ["AMOX500", "AZI500", "METF500", "AMLO5", "LOSA50", "ATOR20", "OMEP20", "CEFA500", "METRO250", "PRED5"])
        m = self.meds[sku]
        fill = {"AZI500": 3}.get(sku, 30 if sku in ("METF500", "AMLO5", "LOSA50", "ATOR20") else 21)
        try:
            rx = await self.api.post("prescription", "/prescriptions", pharm, {
                "branch_id": self.branch_ids[branch], "patient_id": patient["id"], "doctor_id": doctor["id"],
                "rx_no": f"D{day:%m%d}-{n}", "issued_on": day.isoformat(), "notes": "",
                "items": [{"medicine_id": m["id"], "qty_base": fill, "dosage": "1 tablet",
                           "frequency": "3 times a day" if fill == 21 else "once a day", "duration_days": 7 if fill == 21 else 30,
                           "repeats_allowed": 1 if fill == 30 else 0}]}, at=at)  # fmt: skip
            await self.api.post("prescription", f"/prescriptions/{rx['id']}/activate", pharm, at=at)
            strip = next((p for p in m["packs"].values() if not p["is_base"] and p["qty_in_base"] <= fill), m["base"])
            qty = max(1, (fill // strip["qty_in_base"]) - (1 if rng.random() < 0.4 else 0))  # sometimes only part
            line = {"medicine_id": m["id"], "pack_unit_id": strip["id"], "qty": qty, "rx_item_id": rx["items"][0]["id"],
                    "acknowledge_warnings": True}  # fmt: skip
            price = Decimal(strip["sell_price"]) * qty
            body = {"branch_id": self.branch_ids[branch], "lines": [line],
                    "payments": [{"method": "cash", "currency": "USD", "amount": str(math.ceil(price))}]}  # fmt: skip
            try:
                await self.api.post("sales", "/invoices", pharm, body, at=at, key=key("rx", branch, day, n))
            except ApiError as err:
                if err.code != "ALLERGY_WARNING":
                    raise
                line["allergy_override_reason"] = "Tolerated amoxicillin before; doctor confirmed by phone"
                await self.api.post("sales", "/invoices", pharm, body, at=at + timedelta(minutes=2),
                                    key=key("rx-override", branch, day, n))  # fmt: skip
                self.count["allergy_overrides"] += 1
            self.count["rx_sales"] += 1
        except ApiError as err:
            self.count[f"rx_refused:{err.code}"] += 1
            if len(self.failed) < 20:
                self.failed.append(f"rx {branch} {day} {err}")

    async def controlled_sale(self, branch: str, day: date, at: datetime) -> None:
        pharm = self.who[f"{branch}.pharmacist1"]
        patient = [p for p in self.patients if p["branch"] == branch][day.toordinal() % 5]
        sku = "DIAZ5" if day.toordinal() % 3 else "TRAM50"
        m = self.meds[sku]
        try:
            rx = await self.api.post("prescription", "/prescriptions", pharm, {
                "branch_id": self.branch_ids[branch], "patient_id": patient["id"],
                "doctor_id": self.doctors[day.toordinal() % len(self.doctors)]["id"], "rx_no": f"C{day:%m%d}",
                "issued_on": day.isoformat(), "items": [{"medicine_id": m["id"], "qty_base": 10, "dosage": "1 tablet",
                                                         "frequency": "at night", "duration_days": 10}]}, at=at)  # fmt: skip
            await self.api.post("prescription", f"/prescriptions/{rx['id']}/activate", pharm, at=at)
            strip = next(p for p in m["packs"].values() if p["qty_in_base"] == 10)
            pin = await self.api.pin_token(pharm, "controlled.dispense", at=at)
            await self.api.post("sales", "/invoices", pharm, {
                "branch_id": self.branch_ids[branch], "pin_token": pin,
                "lines": [{"medicine_id": m["id"], "pack_unit_id": strip["id"], "qty": 1, "rx_item_id": rx["items"][0]["id"],
                           "patient_id_document": f"KH-ID {patient['phone'][-6:]}", "acknowledge_warnings": True}],
                "payments": [{"method": "cash", "currency": "USD", "amount": str(math.ceil(Decimal(strip["sell_price"])))}]},
                at=at, key=key("ctl", branch, day))  # fmt: skip
            self.count["controlled_sales"] += 1
        except ApiError as err:
            self.count[f"controlled_refused:{err.code}"] += 1
            if len(self.failed) < 20:
                self.failed.append(f"controlled {branch} {day} {err}")

    # ---------------------------------------------------------------- after-sale events

    async def returns_and_cancels(self, branch: str, day: date) -> None:
        rng = self.rng
        today = [i for i in self.invoices[branch] if i["day"] == day and i["pay"] in ("cash_usd", "cash_khr")]
        earlier = [i for i in self.invoices[branch] if i["day"] < day and (day - i["day"]).days <= 14
                   and i["pay"] in ("cash_usd", "cash_khr")]  # fmt: skip
        manager = self.who[f"{branch}.branch_manager1"]
        if today and day.toordinal() % 4 == 0:
            inv = today[-1]
            try:
                await self.api.post("sales", f"/invoices/{inv['id']}/cancel", manager,
                                    {"reason": rng.choice(["Wrong item scanned", "Customer changed their mind",
                                                           "Duplicate sale"])},
                                    at=inv["at"] + timedelta(minutes=10), key=key("cancel", inv["id"]))  # fmt: skip
                self.invoices[branch].remove(inv)
                self.count["cancelled"] += 1
            except ApiError as err:
                self.count[f"cancel_refused:{err.code}"] += 1
        if earlier and day.toordinal() % 2 == 0:
            inv = earlier[(day.toordinal() * 7) % len(earlier)]
            line = inv["lines"][0]
            quarantine = day.toordinal() % 6 == 0
            try:
                await self.api.post("sales", f"/invoices/{inv['id']}/returns", self.who[f"{branch}.pharmacist1"], {
                    "lines": [{"invoice_line_id": line["id"], "qty": 1, "opened": False}], "refund_method": "cash",
                    "to": "quarantine" if quarantine else "stock",
                    "reason": "Damaged box, back to quarantine" if quarantine else "Not needed, unopened"},
                    at=local(day, 16, 20), key=key("return", inv["id"], day))  # fmt: skip
                self.invoices[branch].remove(inv)
                self.count["returns"] += 1
            except ApiError as err:
                self.count[f"return_refused:{err.code}"] += 1

    async def carts_and_orders(self, branch: str, day: date) -> None:
        cashier = self.who[f"{branch}.cashier1"]
        bid = self.branch_ids[branch]
        para, vitc = self.meds["PARA500"], self.meds["VITC500"]
        if day.toordinal() % 3 == 0:
            try:
                await self.api.post("sales", "/carts/suspend", cashier, {"branch_id": bid, "note": "Customer went to the ATM",
                                    "lines": [{"medicine_id": para["id"], "pack_unit_id": para["packs"]["strip"]["id"], "qty": 2}]},
                                    at=local(day, 18, 5))  # fmt: skip
                self.count["suspended"] += 1
            except ApiError as err:
                self.count[f"suspend_refused:{err.code}"] += 1
        if day.weekday() == 1:  # Tuesdays: a clinic orders ahead with a deposit
            clinic = [c for c in self.customers if c["group"] in ("Clinic", "Wholesale")][day.toordinal() % 10]
            manager = self.who[f"{branch}.branch_manager1"]
            lines = [{"medicine_id": para["id"], "pack_unit_id": para["packs"]["box"]["id"], "qty": 2},
                     {"medicine_id": vitc["id"], "pack_unit_id": vitc["packs"]["box"]["id"], "qty": 1}]
            try:
                order = await self.api.post("sales", "/sale-orders", manager, {"branch_id": bid, "customer_id": clinic["id"],
                                            "note": "Weekly clinic order", "lines": lines}, at=local(day, 9, 30))  # fmt: skip
                await self.api.post("sales", f"/sale-orders/{order['id']}/confirm", manager, {
                    "reserve": True, "reserve_days": 3, "deposit": {"method": "cash", "currency": "USD", "amount": "10.00"}},
                    at=local(day, 9, 35), key=key("order-confirm", order["id"]))  # fmt: skip
                self.count["sale_orders"] += 1
                if day.toordinal() % 2 == 0:  # most are collected the next day
                    full = await self.api.get("sales", f"/sale-orders/{order['id']}", manager)
                    total = Decimal(str(full.get("total") or "0"))
                    deposit_id = (full.get("deposit") or {}).get("id") or full.get("deposit_id")
                    pays = [{"method": "deposit", "currency": "USD", "amount": "10.00", "deposit_id": deposit_id}] if deposit_id else []
                    rest = total - (Decimal("10.00") if deposit_id else 0)
                    pays.append({"method": "cash", "currency": "USD", "amount": str(math.ceil(rest))})
                    await self.api.post("sales", f"/sale-orders/{order['id']}/invoice", manager, {
                        "lines": [{"order_line_id": x["id"], "qty": x["qty"]} for x in full["lines"]], "payments": pays},
                        at=local(day + timedelta(days=1), 10, 15), key=key("order-invoice", order["id"]))  # fmt: skip
                    self.count["orders_invoiced"] += 1
            except ApiError as err:
                self.count[f"order_refused:{err.code}"] += 1
                if len(self.failed) < 20:
                    self.failed.append(f"order {branch} {day} {err}")

    async def customer_payments(self, branch: str, day: date) -> None:
        for (b, idx), owed in list(self.owed.items()):
            if b != branch or owed <= 0 or (idx + day.toordinal()) % 3:
                continue
            c = self.customers[idx]
            amount = (owed * Decimal("0.6")).quantize(Decimal("0.01"))
            if amount <= 0:
                continue
            try:
                await self.api.post("customers", "/customer-payments", self.who[f"{branch}.branch_manager1"], {
                    "customer_id": c["id"], "branch_id": self.branch_ids[branch], "method": "cash", "amount": str(amount),
                    "reference": f"Receipt {day:%Y%m%d}"}, at=local(day, 11, 0), key=key("cust-pay", idx, day))  # fmt: skip
                self.owed[(branch, idx)] -= amount
                self.count["customer_payments"] += 1
            except ApiError as err:
                self.count[f"cust_pay_refused:{err.code}"] += 1

    # ---------------------------------------------------------------- warehouse

    async def batch_of(self, branch: str, sku: str, lot: str | None = None, *, at: datetime | None = None) -> dict | None:
        m = self.meds[sku]
        page = await self.api.get("inventory", "/stock", self.who[f"{branch}.branch_manager1"],
                                  params={"branch_id": self.branch_ids[branch], "medicine_id": m["id"]})  # fmt: skip
        for item in page.get("items", []):
            for b in item["batches"]:
                if (lot is None or b["lot_no"] == lot) and b["qty_available"] > 0:
                    return b
        return None

    async def transfer(self, src: str, dst: str, day: date, items: list[tuple[str, int]], short: bool) -> None:
        sender, receiver = self.who[f"{src}.branch_manager1"], self.who[f"{dst}.branch_manager1"]
        at = local(day, 8, 30)
        try:
            t = await self.api.post("inventory", "/transfers", sender, {
                "from_branch_id": self.branch_ids[src], "to_branch_id": self.branch_ids[dst], "note": f"Top-up {dst}",
                "lines": [{"medicine_id": self.meds[s]["id"], "qty_base": q} for s, q in items]}, at=at)  # fmt: skip
            t = await self.api.post("inventory", f"/transfers/{t['id']}/pick", sender, {}, at=at + timedelta(minutes=20))
            t = await self.api.post("inventory", f"/transfers/{t['id']}/dispatch", sender, {},
                                    at=at + timedelta(minutes=40), key=key("dispatch", t["id"]))  # fmt: skip
            recv = [{"pick_id": p["id"], "qty_received": p["qty_base"] - (5 if short and i == 0 else 0)}
                    for i, p in enumerate(t["picks"])]  # fmt: skip
            t = await self.api.post("inventory", f"/transfers/{t['id']}/receive", receiver, {"lines": recv},
                                    at=at + timedelta(hours=4), key=key("receive-transfer", t["id"]))  # fmt: skip
            for d in t.get("discrepancies", []):
                if d.get("status", "open") == "open":
                    await self.api.post("inventory", f"/transfers/{t['id']}/differences/{d['id']}/resolve", sender,
                                        {"resolution": "write_off", "reason": "5 tablets missing in the box, driver confirmed"},
                                        at=at + timedelta(days=1), key=key("resolve", d["id"]))  # fmt: skip
            self.count["transfers"] += 1
        except ApiError as err:
            self.count[f"transfer_refused:{err.code}"] += 1
            if len(self.failed) < 20:
                self.failed.append(f"transfer {src}->{dst} {day} {err}")

    async def shrink(self, branch: str, day: date, sku: str, qty: int, reason: str, lot: str | None = None,
                     controlled: bool = False) -> None:  # fmt: skip
        manager, pharm = self.who[f"{branch}.branch_manager1"], self.who[f"{branch}.pharmacist1"]
        at = local(day, 17, 45)
        try:
            b = await self.batch_of(branch, sku, lot)
            if b is None:
                return
            body: dict[str, Any] = {"branch_id": self.branch_ids[branch], "batch_id": b["batch_id"], "qty_base": min(qty, b["qty_available"]),
                                    "reason": reason, "note": {"damaged": "Box crushed in the delivery", "expired": "Expired on the shelf",
                                                               "broken": "Bottle dropped"}.get(reason, reason)}  # fmt: skip
            if controlled:  # destruction: the pharmacist's PIN and a manager as witness
                body["pin_token"] = await self.api.pin_token(pharm, "inventory.shrinkage", at=at)
                body["witness_token"] = await self.api.witness_token(pharm, manager, "inventory.shrinkage", at=at)
                body["destruction_method"] = "Crushed and mixed with cat litter, witnessed"
                actor = pharm
            else:
                actor = manager
            s = await self.api.post("inventory", "/shrinkages", actor, body, at=at, key=key("shrink", branch, day, sku))
            if s.get("status") == "pending":  # above the limit: someone else approves
                await self.api.post("inventory", f"/shrinkages/{s['id']}/approve", self.who["owner"], {},
                                    at=at + timedelta(hours=1), key=key("shrink-ok", s["id"]))  # fmt: skip
            self.count["shrinkage"] += 1
        except ApiError as err:
            self.count[f"shrink_refused:{err.code}"] += 1
            if len(self.failed) < 20:
                self.failed.append(f"shrink {branch} {sku} {err}")
