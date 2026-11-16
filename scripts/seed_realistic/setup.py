"""Who and what exists: owner, branches, staff (PINs, 2FA), catalog, promotions, suppliers, customers, patients,
doctors, commission. Each step looks for what is already there first (safe to run twice)."""

import asyncio
import random
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from client import Api, ApiError, Person, key
from data import (
    ALLERGIES,
    BRANCHES,
    BRANDS,
    CATEGORIES,
    CLINICS,
    CONDITIONS,
    CUSTOMER_GROUPS,
    EXTRA,
    FAMILY,
    GIVEN,
    HAMPERS,  # fmt: skip
    MEDICINES,
    SPECIALTIES,
    SUPPLIER_GROUPS,
    SUPPLIERS,
)

RATE = 4100


def money(x: float | Decimal) -> str:
    return str(Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def ean13(seed: str) -> str:
    digits = "884" + str(int.from_bytes(seed.encode(), "big") % 10**9).zfill(9)
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(digits))
    return digits + str((10 - total % 10) % 10)


async def all_pages(api: Api, svc: str, path: str, who: Person, size: int = 100, **params: Any) -> list[dict]:  # noqa: ANN401
    out, page = [], 1
    while True:
        r = await api.get(svc, path, who, params={**params, "page": page, "size": size})
        items = r["items"] if isinstance(r, dict) else r
        out += items
        if not isinstance(r, dict) or len(out) >= r.get("total", 0) or not items:
            return out
        page += 1


# ---------------------------------------------------------------- people


def staff_plan(rng: random.Random) -> list[Person]:
    names = [(f"{fk} {gk}", f"{fe} {ge}") for (fk, fe) in FAMILY for (gk, ge) in GIVEN]
    rng.shuffle(names)
    people, n = [], 0
    for b, *_ in BRANCHES:
        for role, count in (("branch_manager", 1), ("pharmacist", 2), ("cashier", 2)):
            for i in range(1, count + 1):
                km, en = names[n]
                n += 1
                phone = f"0{rng.choice('16789')}{rng.randint(1000000, 9999999)}"
                people.append(Person(key=f"{b}.{role}{i}", name=en, name_km=km, phone=phone,
                                     password=f"Demo-{en.split()[1]}-{rng.randint(1000, 9999)}!", role=role, branch=b,
                                     pin=f"{rng.randint(100000, 999999)}",
                                     is_pharmacist=role in ("pharmacist", "branch_manager")))  # fmt: skip
    return people


async def ready_person(api: Api, owner: Person, p: Person, state: dict) -> None:
    """Logs in (setting up 2FA for the roles that need it) and learns the identity headers; PIN set once."""
    p.totp_secret = state.get("totp", {}).get(p.key) or p.totp_secret
    try:
        token = await api.login(p)
    except ApiError as err:
        if err.code not in ("NO_TOTP_SECRET", "INVALID_MFA_CODE"):
            raise
        # 2FA is on but its secret is not in the state file: the owner resets it (PIN), then it is set up again
        pin = await api.pin_token(owner, "auth.mfa_reset")
        await api.post("auth", f"/users/{p.id or await user_id(api, owner, p)}/2fa/reset", owner, {"pin_token": pin})
        p.totp_secret = None
        token = await api.login(p)
    me = await api.bearer("GET", "/me", token)
    if me.get("mfa_setup_required") or (p.role in ("owner", "branch_manager") and not me.get("totp_enabled")):
        setup = await api.bearer("POST", "/2fa/setup", token)
        p.totp_secret = setup["secret"]
        await api.bearer("POST", "/2fa/enable", token, {"code": await api._code(p.totp_secret)})  # noqa: SLF001
        state.setdefault("totp", {})[p.key] = p.totp_secret
        token = await api.login(p)
        me = await api.bearer("GET", "/me", token)
    if not me.get("has_pin"):
        await api.bearer("PUT", "/me/pin", token, {"password": p.password, "pin": p.pin})
    await api.identify(p, token)


async def user_id(api: Api, owner: Person, p: Person) -> str:
    users = await all_pages(api, "auth", "/users", owner, q=p.phone)
    return next(u["id"] for u in users if u["phone"] == p.phone)


async def branches(api: Api, owner: Person) -> dict[str, dict]:
    have = {b["code"]: b for b in await api.get("branch", "/branches", owner, params={"include_inactive": True})}
    for code, name_en, name_km, address, phone, header in BRANCHES:
        if code not in have:
            have[code] = await api.post("branch", "/branches", owner, {
                "code": code, "name_en": f"Pharmacy {name_en}", "name_km": f"ឱសថស្ថាន {name_km}", "address": address,
                "phone": phone})  # fmt: skip
        await api.put("branch", f"/branches/{have[code]['id']}/settings", owner, {
            "receipt_header": header, "receipt_footer": "សូមអរគុណ · Thank you · Get well soon",
            "allow_opened_pack_returns": True, "receipt_lang": "km"})  # fmt: skip
    return have


async def exchange_rates(api: Api, owner: Person, branch_ids: dict[str, str], at: datetime) -> None:
    for bid in branch_ids.values():
        await api.put("sales", f"/exchange-rates/{bid}", owner, {"khr_per_usd": RATE}, at=at)


async def staff(api: Api, owner: Person, people: list[Person], branch_ids: dict[str, str], state: dict) -> None:
    existing = {u["phone"]: u for u in await all_pages(api, "auth", "/users", owner)}
    for p in people:
        if p.phone in existing:
            p.id = existing[p.phone]["id"]
            continue
        made = await api.post("auth", "/users", owner, {
            "name": p.name, "phone": p.phone, "password": p.password, "role": p.role, "locale": "km",
            "is_pharmacist": p.is_pharmacist, "branch_ids": [branch_ids[p.branch]] if p.branch else []})  # fmt: skip
        p.id = made["id"]
    # each 2FA person has their own secret, so their (30 s) code waits run side by side
    await asyncio.gather(*(ready_person(api, owner, p, state) for p in people))


# ---------------------------------------------------------------- catalog


async def lookups(api: Api, owner: Person) -> tuple[dict, dict]:
    cats = {c["name_en"]: c for c in await api.get("catalog", "/categories", owner, params={"include_inactive": True})}
    for _, en, km in CATEGORIES:
        if en not in cats:
            cats[en] = await api.post("catalog", "/categories", owner, {"name_en": en, "name_km": km})
    brands = {b["name_en"]: b for b in await api.get("catalog", "/brands", owner, params={"include_inactive": True})}
    for en, km in BRANDS:
        if en not in brands:
            brands[en] = await api.post("catalog", "/brands", owner, {"name_en": en, "name_km": km})
    by_code = {code: cats[en]["id"] for code, en, _ in CATEGORIES}
    return by_code, {en: b["id"] for en, b in brands.items()}


def base_unit(form: str) -> str:
    if form in ("tablet", "capsule", "sachet", "lozenge", "patch", "vial", "gummy"):
        return form
    if form in ("cream", "gel", "ointment"):
        return "tube"
    if form in ("effervescent",):
        return "tablet"
    liquid = ("syrup", "solution", "lotion", "shampoo", "oil", "eye drops", "ear drops", "nasal spray", "nasal drops",
              "spray", "bottle")  # fmt: skip
    return "bottle" if form in liquid else "pack" if form in ("pack", "powder") else "piece"


def catalog_rows() -> list[dict]:
    rows = []
    for (sku, brand, generic, strength, form, km, cat, owner, rx, schedule, classes, base, price, packs, pop) in MEDICINES:
        rows.append(dict(sku=sku, brand=brand, generic=generic, strength=strength, form=form, km=km, cat=cat, owner=owner,
                         rx=rx, schedule=schedule, classes=classes, base=base, price=price, packs=packs, pop=pop))  # fmt: skip
    for (sku, brand, generic, strength, form, km, cat, owner, price, packs, pop) in EXTRA:
        rows.append(dict(sku=sku, brand=brand, generic=generic, strength=strength, form=form, km=km, cat=cat, owner=owner,
                         rx=False, schedule=None, classes=[], base=base_unit(form),
                         price=price, packs=packs, pop=pop))  # fmt: skip
    return rows


async def medicines(api: Api, owner: Person, cats: dict, brands: dict) -> dict[str, dict]:
    have = {m["sku"]: m for m in await all_pages(api, "catalog", "/medicines", owner, include_inactive=True)}
    rows = catalog_rows()

    async def make(r: dict) -> None:
        if r["sku"] in have:
            return
        base = {"tablet": "tablet", "capsule": "capsule"}.get(r["base"], r["base"])
        have[r["sku"]] = await api.post("catalog", "/medicines", owner, {
            "sku": r["sku"], "brand_name": r["brand"], "generic_name": r["generic"], "strength": r["strength"],
            "dosage_form": r["form"], "name_km": r["km"], "category_id": cats[r["cat"]], "brand_id": brands[r["owner"]],
            "manufacturer": r["owner"], "base_unit": base, "base_price": money(r["price"]),
            "base_barcode": ean13(r["sku"] + ":base"), "is_rx_only": r["rx"], "controlled_schedule": r["schedule"],
            "storage": "cold" if r["sku"] in ("PROBIO",) else "room", "reorder_level": 20,
            "drug_classes": r["classes"],
            "pack_units": [{"name": n, "qty_in_base": q, "sell_price": money(p), "barcode": ean13(f"{r['sku']}:{n}")}
                           for n, q, p in r["packs"]]})  # fmt: skip

    await asyncio.gather(*(make(r) for r in rows))
    for sku, name, km, price, parts in HAMPERS:
        if sku not in have:
            have[sku] = await api.post("catalog", "/hampers", owner, {
                "sku": sku, "name": name, "name_km": km, "price": money(price), "category_id": cats["FIRST"],
                "barcode": ean13(sku), "components": [{"medicine_id": have[s]["id"], "qty_base": q} for s, q in parts]})  # fmt: skip
    fresh = {m["sku"]: m for m in await all_pages(api, "catalog", "/medicines", owner, include_inactive=True)}
    info = {r["sku"]: r for r in rows}
    parts = {h[0]: h[4] for h in HAMPERS}
    out = {}
    for sku, m in fresh.items():
        packs = {p["name"]: p for p in m.get("pack_units", []) if p.get("is_active", True)}
        out[sku] = {"id": m["id"], "packs": packs, "base": next(p for p in packs.values() if p["is_base"]) if packs else None,
                    "rx": m.get("is_rx_only"), "controlled": bool(m.get("controlled_schedule")),
                    "hamper": m.get("kind") == "hamper", "row": info.get(sku), "category_id": m.get("category_id"),
                    "components": parts.get(sku, [])}  # fmt: skip
    return out


async def promotions(api: Api, owner: Person, meds: dict, cats: dict, start: datetime) -> None:
    have = {p["code"] for p in await api.get("catalog", "/promotions", owner)}
    wanted = [
        {"code": "ORS-B2G1", "name": "ORS: buy 2 get 1", "name_km": "អូរ៉េសូល ទិញ ២ ថែម ១", "type": "buy_x_get_y",
         "buy_qty": 2, "get_qty": 1, "medicine_ids": [meds["ORS"]["id"]]},
        {"code": "VIT-10", "name": "Vitamins 10% off", "name_km": "វីតាមីន បញ្ចុះ ១០%", "type": "percent_off",
         "value": "10", "category_ids": [cats["VIT"]]},
    ]
    for p in wanted:
        if p["code"] not in have:
            await api.post("catalog", "/promotions", owner, {**p, "starts_at": start.isoformat(), "stackable": False,
                                                             "branch_ids": []})  # fmt: skip


# ---------------------------------------------------------------- contacts


async def suppliers(api: Api, owner: Person) -> dict[str, dict]:
    groups = {g["name_en"]: g for g in await api.get("purchasing", "/supplier-groups", owner, params={"include_inactive": True})}
    for en, km in SUPPLIER_GROUPS:
        if en not in groups:
            groups[en] = await api.post("purchasing", "/supplier-groups", owner, {"name_en": en, "name_km": km})
    have = {s["code"]: s for s in await all_pages(api, "purchasing", "/suppliers", owner, include_inactive=True)}
    for code, name, km, phone, terms, g in SUPPLIERS:
        if code not in have:
            have[code] = await api.post("purchasing", "/suppliers", owner, {
                "code": code, "name": name, "name_km": km, "phone": phone, "payment_terms_days": terms,
                "address": "Phnom Penh", "group_id": groups[SUPPLIER_GROUPS[g][0]]["id"]})  # fmt: skip
    return have


async def customers(api: Api, owner: Person, rng: random.Random) -> list[dict]:
    groups = {g["name_en"]: g for g in await api.get("customers", "/customer-groups", owner, params={"include_inactive": True})}
    for en, km, pct in CUSTOMER_GROUPS:
        if en not in groups:
            groups[en] = await api.post("customers", "/customer-groups", owner, {"name_en": en, "name_km": km,
                                                                                 "default_discount_pct": pct})  # fmt: skip
    have = {c["phone"]: c for c in await all_pages(api, "customers", "/customers", owner, include_inactive=True)}
    out = []
    for i in range(80):
        (fk, fe), (gk, ge) = FAMILY[i % len(FAMILY)], GIVEN[(i * 7) % len(GIVEN)]
        group = "Clinic" if i < 5 else "Wholesale" if i < 10 else "Retail"
        name = CLINICS[i] if group == "Clinic" else f"{fe} {ge}" + (" Pharmacy" if group == "Wholesale" else "")
        phone = f"097{7000000 + i * 1373:07d}"
        limit = "500.00" if group != "Retail" else ("50.00" if i % 4 == 0 else "0")
        if phone not in have:
            have[phone] = await api.post("customers", "/customers", owner, {
                "phone": phone, "name": name, "name_km": f"{fk} {gk}" if group == "Retail" else "",
                "group_id": groups[group]["id"], "credit_limit": limit})  # fmt: skip
        out.append({**have[phone], "group": group, "credit": Decimal(limit)})
    return out


async def doctors(api: Api, owner: Person) -> list[dict]:
    have = {d["licence_no"]: d for d in await all_pages(api, "prescription", "/doctors", owner, size=200, include_inactive=True)}
    out = []
    for i in range(10):
        (_fk, fe), (_gk, ge) = FAMILY[(i + 3) % len(FAMILY)], GIVEN[(i * 3 + 1) % len(GIVEN)]
        lic = f"MOH-KH-{2010 + i}-{1000 + i * 37}"
        if lic not in have:
            have[lic] = await api.post("prescription", "/doctors", owner, {
                "name": f"Dr. {fe} {ge}", "licence_no": lic, "specialty": SPECIALTIES[i % len(SPECIALTIES)],
                "clinic": CLINICS[i % len(CLINICS)], "phone": f"012{3000000 + i * 911:07d}"})  # fmt: skip
        out.append(have[lic])
    return out


async def patients(api: Api, owner: Person, branch_ids: dict[str, str], rng: random.Random) -> list[dict]:
    have = {p.get("phone"): p for p in await all_pages(api, "prescription", "/patients", owner, size=200, include_inactive=True)}
    codes = list(branch_ids)
    out = []
    for i in range(40):
        (fk, fe), (gk, ge) = FAMILY[(i * 5) % len(FAMILY)], GIVEN[(i * 11 + 2) % len(GIVEN)]
        phone = f"096{5000000 + i * 2711:07d}"
        branch = codes[i % len(codes)]
        allergies = [{"kind": k, "value": v, "note": "rash"} for k, v in ([ALLERGIES[i % len(ALLERGIES)]] if i % 3 == 0 else [])]
        if phone not in have:
            have[phone] = await api.post("prescription", "/patients", owner, {
                "branch_id": branch_ids[branch], "name_km": f"{fk} {gk}", "name_en": f"{fe} {ge}",
                "sex": "female" if i % 2 else "male", "dob": f"{1950 + (i * 7) % 55}-{1 + i % 12:02d}-{1 + i % 27:02d}",
                "phone": phone, "chronic_conditions": CONDITIONS[i % len(CONDITIONS)], "allergies": allergies})  # fmt: skip
        out.append({**have[phone], "branch": branch, "allergies": allergies})
    return out


async def commission(api: Api, owner: Person, start: datetime) -> None:
    rules = await api.get("sales", "/commission/rules", owner)
    if not any(r["name"] == "Everyone 2%" for r in (rules.get("items", rules) if isinstance(rules, dict) else rules)):
        await api.post("sales", "/commission/rules", owner, {"name": "Everyone 2%", "kind": "percent", "value": "2",
                                                             "scope": "all", "starts_on": start.date().isoformat()})  # fmt: skip


def day_at(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def back(days: int, base: datetime) -> datetime:
    return base - timedelta(days=days)


__all__ = ["key"]
