"""make seed-realistic: a realistic Cambodian pharmacy (3 branches, 90 days) made ONLY through the services' APIs.

    docker compose run … sales python main.py           # seed (safe to repeat: what exists is skipped)
    docker compose run … sales python main.py verify    # register chains valid, no open register discrepancy

Refused unless APP_ENV=development (and never in production). Fixed random seed: the same data every run.
Back-dated calls use the dev clock (pharmacy_shared.clock), honoured only in development.
Output in /out (seed-output/<compose project>/ on the host, git-ignored): logins.md (the login table) and state.json.
Settings: SEED_DAYS (90), SEED_MIN / SEED_MAX invoices per branch per day (40 / 120), SEED_OWNER_PHONE /
SEED_OWNER_PASSWORD (the owner `make seed-realistic` creates), SEED_OWNER_TOTP (an owner who already has 2FA).
"""

import asyncio
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import history
import setup
import stock
from client import Api, ApiError, Person, key

PP = ZoneInfo("Asia/Phnom_Penh")
OUT = Path(os.environ.get("SEED_OUT", "/out"))
STATE = OUT / "state.json"


def log(msg: str, t0: float) -> None:
    print(f"[{time.monotonic() - t0:7.1f}s] {msg}", flush=True)


def guard() -> None:
    if os.environ.get("APP_ENV") != "development" or os.environ.get("ENVIRONMENT") == "production":
        sys.exit("seed-realistic refused: it runs only with APP_ENV=development (never in production)")
    if not os.environ.get("SERVICE_TOKEN"):
        sys.exit("seed-realistic: SERVICE_TOKEN is not set (run it through make seed-realistic)")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, default=str))


def logins(owner: Person, people: list[Person], out: Path) -> None:
    rows = ["# Demo logins (make seed-realistic) — development only, never real data", "",
            "Web app: http://localhost · log in with the phone number. Owner and branch managers use an authenticator app:",
            "add the TOTP secret below as a manual key (time-based, 6 digits, 30 s).", "",
            "| Who | Name | Role | Branch | Phone | Password | PIN | 2FA secret |", "|---|---|---|---|---|---|---|---|"]
    for p in [owner, *people]:
        rows.append(f"| {p.key} | {p.name} / {p.name_km} | {p.role} | {p.branch or 'all'} | {p.phone} | `{p.password}` | "
                    f"{p.pin} | {('`' + p.totp_secret + '`') if p.totp_secret else '—'} |")
    rows += ["", "otpauth links (paste into an authenticator that takes links):", ""]
    for p in [owner, *people]:
        if p.totp_secret:
            rows.append(f"- {p.key}: otpauth://totp/Pharmacy:{p.phone}?secret={p.totp_secret}&issuer=Pharmacy")
    out.write_text("\n".join(rows) + "\n")


async def stock_take(api: Api, trade: history.Trade, branch: str, cats: dict) -> None:
    """One approved stock take per branch (eye & ear shelf): pharmacist counts, a manager double-counts."""
    if f"count:{branch}" in trade.state.setdefault("done", []):
        return
    pharm, manager = trade.who[f"{branch}.pharmacist2"], trade.who[f"{branch}.branch_manager1"]
    count = None
    for shelf in ("EYE", "PARA", "WOMEN", "SKIN", "FIRST", "VIT", "PAIN"):  # a small shelf that has stock
        try:
            count = await api.post("stockcount", "/counts", manager, {"branch_id": trade.branch_ids[branch], "scope": "category",
                                   "category_id": cats[shelf], "note": f"Quarterly count: {shelf} shelf"})  # fmt: skip
            break
        except ApiError as err:
            if err.code != "VALIDATION_ERROR":
                raise
    if count is None:
        return
    view = await api.get("stockcount", f"/counts/{count['id']}", pharm)
    page = await api.get("inventory", "/stock", manager, params={"branch_id": trade.branch_ids[branch], "size": 100,
                                                                "q": ""})  # fmt: skip
    on_hand = {(i["sku"], b["lot_no"]): b["qty_on_hand"] for i in page.get("items", []) for b in i["batches"]}
    for line in view["lines"]:
        qty = on_hand.get((line["sku"], line["lot_no"]), 0)
        await api.post("stockcount", f"/counts/{count['id']}/entries", pharm, {"line_id": line["id"], "qty": qty})
        if line.get("needs_double"):
            await api.post("stockcount", f"/counts/{count['id']}/entries", manager, {"line_id": line["id"], "qty": qty})
    await api.post("stockcount", f"/counts/{count['id']}/submit", pharm)
    try:
        await api.post("stockcount", f"/counts/{count['id']}/approve", manager, {}, key=key("count-approve", count["id"]))
    except ApiError as err:
        if err.code != "PIN_REQUIRED":
            raise
        pin = await api.pin_token(manager, "stockcount.approve")
        await api.post("stockcount", f"/counts/{count['id']}/approve", manager, {"pin_token": pin},
                       key=key("count-approve-pin", count["id"]))  # fmt: skip
    trade.state["done"].append(f"count:{branch}")


async def seed() -> None:
    guard()
    t0 = time.monotonic()
    rng = random.Random(20261112)  # fixed: the same demo every run
    state = load_state()
    days_n = int(os.environ.get("SEED_DAYS", "90"))
    lo, hi = int(os.environ.get("SEED_MIN", "40")), int(os.environ.get("SEED_MAX", "120"))
    real_now = datetime.now(PP)
    real_today = real_now.date()
    days = [real_today - timedelta(days=k) for k in range(days_n, 0, -1)]
    state["days_n"] = days_n
    start = history.local(days[0] - timedelta(days=7), 8, 0)  # set-up a week before the first sale
    api = Api(concurrency=int(os.environ.get("SEED_CONCURRENCY", "24")))
    owner = Person(key="owner", name="Owner Demo", name_km="ម្ចាស់ ឱសថស្ថាន", role="owner", branch=None,
                   phone=os.environ.get("SEED_OWNER_PHONE", "012000111"),
                   password=os.environ.get("SEED_OWNER_PASSWORD", "Demo-Owner-2026!"), pin="246810",
                   totp_secret=os.environ.get("SEED_OWNER_TOTP") or None)  # fmt: skip
    try:
        await setup.ready_person(api, owner, owner, state)
        if state.get("owner_id") not in (None, owner.id):
            state = {"totp": {"owner": owner.totp_secret}, "days_n": days_n}  # another stack (down -v): start again
        state["owner_id"] = owner.id
        save_state(state)
        log("owner ready", t0)

        branches = await setup.branches(api, owner)
        branch_ids = {code: branches[code]["id"] for code, *_ in setup.BRANCHES}
        await setup.exchange_rates(api, owner, branch_ids, start - timedelta(days=1))
        people = setup.staff_plan(rng)
        await setup.staff(api, owner, people, branch_ids, state)
        save_state(state)
        who = {p.key: p for p in people} | {"owner": owner}
        logins(owner, people, OUT / "logins.md")
        log(f"branches {list(branch_ids)} and {len(people)} staff ready (logins in seed-output/<project>/logins.md)", t0)

        cats, brands = await setup.lookups(api, owner)
        meds = await setup.medicines(api, owner, cats, brands)
        await setup.promotions(api, owner, meds, cats, start)
        log(f"catalog: {len(meds)} products ({sum(m['rx'] for m in meds.values())} Rx-only, "
            f"{sum(m['controlled'] for m in meds.values())} controlled, {sum(m['hamper'] for m in meds.values())} hampers)", t0)
        suppliers = await setup.suppliers(api, owner)
        customers = await setup.customers(api, owner, rng)
        doctors = await setup.doctors(api, owner)
        patients = await setup.patients(api, owner, branch_ids, rng)
        await setup.commission(api, owner, start)
        log(f"{len(suppliers)} suppliers, {len(customers)} customers, {len(patients)} patients, {len(doctors)} doctors", t0)

        sellers = {b: [f"{b}.cashier1", f"{b}.cashier2", f"{b}.pharmacist1", f"{b}.pharmacist2"] for b in branch_ids}
        plan = history.plan_sales(meds, list(branch_ids), sellers, customers, days, lo, hi, rng)
        half = days[len(days) // 2]
        rx_extra = {(b, s): 200 for b in branch_ids for s in ("AMOX500", "AZI500", "METF500", "AMLO5", "LOSA50", "ATOR20",
                                                               "OMEP20", "CEFA500", "METRO250", "PRED5")}  # fmt: skip
        rx_extra |= {(b, s): 150 for b in branch_ids for s in ("DIAZ5", "TRAM50")}
        first = history.demand([s for s in plan if s.day < half], meds, rx_extra)
        second = history.demand([s for s in plan if s.day >= half], meds, rx_extra)
        log(f"plan: {len(plan)} sales over {len(days)} days", t0)

        await stock.initialize(api, who["SR1.branch_manager1"], owner, "SR1", branch_ids["SR1"], meds, first, start,
                               real_today, state)  # fmt: skip
        await stock.stock_wave(api, who, branch_ids, suppliers, meds, first, 1, start, real_today, state, ["PP1", "PP2"])
        save_state(state)
        log("stock received (wave 1) and SR1 initialized", t0)

        trade = history.Trade(api, who, branch_ids, meds, customers, patients, doctors, rng, state)
        by_day: dict[date, list[history.Sale]] = {}
        for s in plan:
            by_day.setdefault(s.day, []).append(s)
        done_days = set(state.setdefault("days", []))
        for i, day in enumerate(days):
            if day == half and "wave2" not in done_days:
                await stock.stock_wave(api, who, branch_ids, suppliers, meds, second, 2,
                                       history.local(day - timedelta(days=1), 9, 0), real_today, state,
                                       list(branch_ids))  # fmt: skip
                await stock.pay_suppliers(api, who, branch_ids, suppliers, history.local(day, 15, 0),
                                          {"PP1": 1.0, "PP2": 0.6, "SR1": 1.0}, state, "first")  # fmt: skip
                state["days"].append("wave2")
                save_state(state)
            if day.isoformat() in done_days:
                continue
            await trade.run_day(by_day.get(day, []))
            jobs = []
            for b in branch_ids:
                jobs += [trade.rx_sale(b, day, n, history.local(day, 10 + 3 * n, 15)) for n in range(2)]
                if day.weekday() == 3:
                    jobs.append(trade.controlled_sale(b, day, history.local(day, 15, 40)))
                jobs += [trade.returns_and_cancels(b, day), trade.carts_and_orders(b, day)]
                if day.weekday() == 5:
                    jobs.append(trade.customer_payments(b, day))
            await asyncio.gather(*jobs)
            if i == len(days) // 3:
                await trade.transfer("PP1", "PP2", day, [("PARA500", 240), ("CETI10", 100), ("ORS", 60)], short=True)
            if i == 2 * len(days) // 3:
                await trade.transfer("PP2", "SR1", day, [("PARA500", 120), ("ORS", 40), ("CETI10", 50)], short=False)
            if i == len(days) // 2 + 5:
                await trade.shrink("PP1", day, "CALPOL", 2, "broken")
                await trade.shrink("PP2", day, "BETADINE", 3, "damaged")
            if i == len(days) - 10:
                await trade.shrink("PP1", day, "DIAZ5", 10, "damaged", controlled=True)
            if day > real_today - timedelta(days=min(12, max(1, days_n // 4))) and "shrink-expired" not in state.setdefault("done", []):
                await trade.shrink("PP1", day, "VITC500", 9999, "expired", lot="VITC-EXP1")
                state["done"].append("shrink-expired")
            state["days"].append(day.isoformat())
            save_state(state)
            if i % 5 == 4 or i == len(days) - 1:
                log(f"{day}: {trade.count['sales']} sales so far, {api.calls} API calls", t0)

        # today, in real time
        await stock.pay_suppliers(api, who, branch_ids, suppliers, real_now - timedelta(days=3),
                                  {"PP1": 0.5, "PP2": 0.0, "SR1": 0.3}, state, "second")  # fmt: skip
        month = (real_today.replace(day=1) - timedelta(days=1)).replace(day=1)
        for b, bid in branch_ids.items():
            try:
                await api.post("sales", f"/commission/periods/{bid}/{month.isoformat()}/close", owner)
            except ApiError as err:
                if err.status not in (409,):
                    raise
            await stock_take(api, trade, b, cats)
        if "recall" not in state["done"]:
            lot = await trade.batch_of("PP2", "CETI10", "CETI-RECALL") or await trade.batch_of("PP2", "CETI10")
            if lot:
                try:
                    await api.post("inventory", "/recalls", owner, {"medicine_id": meds["CETI10"]["id"],
                                   "lot_nos": [lot["lot_no"]], "reason": "Manufacturer recall: tablet discolouration",
                                   "source": "Supplier notice"}, key=key("recall", lot["lot_no"]))  # fmt: skip
                except ApiError as err:
                    if err.status != 409:
                        raise
            state["done"].append("recall")
        save_state(state)
        logins(owner, people, OUT / "logins.md")
        summary = dict(sorted(trade.count.items()))
        log(f"done: {json.dumps(summary)}", t0)
        for f in trade.failed[:10]:
            print("  refused:", f[:300])
        print(f"API calls: {api.calls}.\n")
        print((OUT / "logins.md").read_text())  # the login table (demo accounts, development only)
        print("Saved as seed-output/<project>/logins.md")
    finally:
        await api.close()


async def verify() -> int:
    """The controlled register: every chain valid, no open discrepancy (after `controlled … cli check`)."""
    guard()
    state = load_state()
    api = Api()
    owner = Person(key="owner", name="Owner Demo", name_km="", role="owner", branch=None,
                   phone=os.environ.get("SEED_OWNER_PHONE", "012000111"),
                   password=os.environ.get("SEED_OWNER_PASSWORD", "Demo-Owner-2026!"), pin="246810",
                   totp_secret=os.environ.get("SEED_OWNER_TOTP") or state.get("totp", {}).get("owner"))  # fmt: skip
    try:
        await setup.ready_person(api, owner, owner, state)
        bad = 0
        for b in await api.get("branch", "/branches", owner):
            v = await api.get("controlled", "/register/verify", owner, params={"branch_id": b["id"]})
            ok = v.get("valid")
            chains = v.get("chains") or []
            entries = sum(int(c.get("entries") or c.get("checked") or 0) for c in chains)
            print(f"register {b['code']}: {'valid' if ok else 'BROKEN'} – {len(chains)} chains, {entries} entries")
            bad += 0 if ok else 1
        open_ = await api.get("controlled", "/discrepancies", owner, params={"status": "open"})
        items = open_.get("items", open_) if isinstance(open_, dict) else open_
        print(f"open register discrepancies (register vs stock): {len(items)}")
        return 1 if bad or items else 0
    finally:
        await api.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        sys.exit(asyncio.run(verify()))
    asyncio.run(seed())
