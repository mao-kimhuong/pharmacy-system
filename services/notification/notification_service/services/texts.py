"""Message texts. Built ONLY from the allow-listed fields below: numbers, branch
codes and names, product SKU and name, staff display names, invoice numbers.
Patient names, patient IDs, Rx numbers, doctors and customer names are never
read here, so they can never reach a chat (tests/test_notification.py checks
every template with an invoice full of patient data)."""

from typing import Any

SAFE_LINE_FIELDS = ("sku", "name", "qty", "pack_unit", "line_total", "net", "cost", "manual_discount",
                    "promo_discount")  # fmt: skip


def safe_line(line: dict[str, Any]) -> dict[str, Any]:
    return {k: line.get(k) for k in SAFE_LINE_FIELDS}


def _change(now: str, before: str) -> str:
    a, b = float(now), float(before)
    if not b:
        return ""
    return f" ({(a - b) * 100 / b:+.0f}% vs last week)"


def daily_summary(title: str, figures: dict[str, Any], profit: bool) -> str:
    t, week = figures["today"], figures["same_day_last_week"]
    out = [f"📊 {title} – {t['date']}",
           f"Sales: {t['net_sales']} USD / {t['net_sales_khr']:,} KHR{_change(t['net_sales'], week['net_sales'])}",
           f"Invoices: {t['invoices']} · average basket {t['average_basket']} USD",
           f"Returns: {t['returns']} USD"]  # fmt: skip
    if profit and "gross_profit" in t:
        out.append(f"Gross profit: {t['gross_profit']} USD ({t.get('margin_pct') or 0}%)")
    top = figures.get("top_medicines") or []
    if top:
        out.append("Top: " + ", ".join(f"{x['sku']} {x['net']}" for x in top[:5]))
    pending = figures.get("pending_approvals") or {}
    waiting = sum(int(v) for v in pending.values())
    out += [f"Low stock: {len(figures.get('low_stock') or [])} · near expiry: {figures['near_expiry']['count']}",
            f"Controlled discrepancies open: {figures.get('open_controlled_discrepancies', 0)}",
            f"Waiting for approval: {waiting}"]  # fmt: skip
    return "\n".join(out)


def stock_digest(branch: str, low: list[dict[str, Any]], expiring: list[dict[str, Any]]) -> str:
    out = [f"📦 {branch} – stock to look at"]
    if low:
        out.append(f"Low stock ({len(low)}):")
        out += [f"• {x.get('sku')} {x.get('name') or ''}: {x.get('available')} left, point {x.get('reorder_point')}"
                for x in low[:25]]  # fmt: skip
    if expiring:
        out.append(f"Expiring soon ({len(expiring)}):")
        out += [f"• {x.get('sku')} lot {x.get('lot_no')}: {x.get('qty_base')} expire {x.get('expiry_date')} "
                f"({x.get('days_left')} days)" for x in sorted(expiring, key=lambda e: e.get("days_left") or 0)[:25]]  # fmt: skip
    return "\n".join(out)


def discrepancy(branch: str, p: dict[str, Any], sku: str) -> str:
    return (f"⚠️ {branch}: controlled register and stock disagree for {sku} lot {p.get('lot_no')}: "
            f"register {p.get('register_qty')}, stock {p.get('stock_qty')}.")  # fmt: skip


def chain_broken(branch: str, sku: str) -> str:
    return f"🚨 {branch}: the controlled register hash chain for {sku} is broken. Check it now."


def locked(name: str, what: str) -> str:
    return f"🔒 {name}'s {what} is locked after too many wrong tries."


def two_factor(name: str, turned_off: bool, by: str) -> str:
    """Name and what happened only: never a key, a code or an address."""
    what = "turned off two-factor login" if turned_off else {
        "self": "changed their two-factor key", "owner": "had two-factor login reset by the owner",
        "server": "had two-factor login reset on the server"}.get(by, "had two-factor login reset")  # fmt: skip
    return f"🛡 {name} {what}."


def money_alert(branch: str, number: str, staff: str, kind: str, lines: list[dict[str, Any]], show_cost: bool) -> str:
    """Cost only in the owner's chat (choice H)."""
    head = {"below_cost": "sold below cost", "large_discount": "large discount"}[kind]
    body = [f"💸 {branch} {number} by {staff}: {head}"]
    for x in (safe_line(x) for x in lines[:10]):
        cost = f", cost {x['cost']}" if show_cost else ""
        body.append(f"• {x['sku']} {x['name']} ×{x['qty']} {x['pack_unit']}: list {x['line_total']}, "
                    f"net {x['net']}{cost}, manual discount {x['manual_discount']}")  # fmt: skip
    return "\n".join(body)


def khqr_refund(branch: str, p: dict[str, Any]) -> str:
    how = ("refund it at the bank, then confirm it in Sales → KHQR Refunds" if p.get("provider") == "bakong"
           else "refund it in Sales → KHQR Refunds (PIN)")  # fmt: skip
    return (f"↩️ {branch}: KHQR payment of {p.get('amount')} {p.get('currency')} (bank ref {p.get('bank_ref') or '-'}) "
            f"was not used by a completed sale: {how}.")  # fmt: skip


def khqr_review(branch: str, p: dict[str, Any]) -> str:
    return (f"⚠️ {branch}: a KHQR for {p.get('amount')} {p.get('currency')} was paid {p.get('paid_amount')} "
            f"{p.get('paid_currency')} (bank ref {p.get('bank_ref') or '-'}). Not taken for the sale: a manager "
            "checks it in Sales → KHQR Refunds.")  # fmt: skip


KHQR_METHOD = {"payway": "by ABA PayWay", "by_hand": "at the bank (confirmed)", "fake": "(test)"}


def khqr_refunded(branch: str, p: dict[str, Any]) -> str:
    return (f"✅ {branch}: KHQR refund of {p.get('amount')} {p.get('currency')} {KHQR_METHOD.get(p.get('method'), '')} "
            f"(bank ref {p.get('bank_ref') or '-'}).").replace("  ", " ")  # fmt: skip


KHQR_KINDS = {"not_paid_at_provider": "recorded as paid, not paid at the bank",
              "paid_not_recorded": "paid at the bank, not recorded", "amount_mismatch": "amount differs",
              "refund_mismatch": "refunds differ", "paid_not_used": "paid, no sale took it",
              "refund_open": "refund still due"}  # fmt: skip


def khqr_reconciled(branch: str, p: dict[str, Any]) -> str:
    kinds = p.get("kinds") or {}
    body = ", ".join(f"{n} {KHQR_KINDS.get(k, k)}" for k, n in sorted(kinds.items()))
    return f"🔎 {branch}: KHQR check of {p.get('date')}: {p.get('issues')} to look at ({body}). Sales → KHQR Refunds."


# ------------------------------------------------------------------ T2 approvals (staff chats: Khmer, then English)

APPROVAL_KIND = {
    "shrinkage": ("ការកាត់ចេញពីស្តុក", "Shrinkage"),
    "count": ("ការរាប់ស្តុក", "Stock take"),
    "transfer_request": ("សំណើផ្ទេរ", "Transfer request"),
    "purchase_request": ("សំណើទិញ", "Purchase request"),
    "discount": ("ការបញ្ចុះតម្លៃលើសកំណត់", "Discount above the cap"),
}
WHY_APP = {
    "controlled": ("ថ្នាំគ្រប់គ្រង", "controlled medicine"),
    "pin": ("ត្រូវការ PIN", "needs a PIN"),
    "limit": ("លើសដែនកំណត់ Telegram", "above the Telegram limit"),
    "unknown": ("មិនដឹងតម្លៃ", "value not known"),
}


def approval(kind: str, branch: str, number: str, who: str, d: dict[str, Any], value: str | None,
             why_app: str | None, link: str | None) -> str:  # fmt: skip
    """value: only in the owner's chat when it is a cost (stock values); a discount amount shows everywhere."""
    km, en = APPROVAL_KIND[kind]
    if kind == "shrinkage":
        what = (f"{d.get('qty_base')} · lot {d.get('lot_no')} · {d.get('reason')}",) * 2
    elif kind == "count":
        n = d.get("lines", 0)
        what = (f"{n} ជួរមានភាពខុសគ្នា", f"{n} line(s) with a variance")
    elif kind == "transfer_request":
        n = d.get("lines", 0)
        what = (f"{n} មុខ ពី {d.get('from')} ទៅ {d.get('to')}", f"{n} item(s) from {d.get('from')} to {d.get('to')}")
    elif kind == "purchase_request":
        n = d.get("lines", 0)
        what = (f"{n} មុខ", f"{n} item(s)")
    else:
        what = (f"{d.get('pct')}% (កំណត់ {d.get('cap')}%) · {d.get('discount')} USD លើការលក់ {d.get('total')} USD",
                f"{d.get('pct')}% (cap {d.get('cap')}%) · {d.get('discount')} USD on a {d.get('total')} USD sale")  # fmt: skip
    lines = [f"🟡 ត្រូវការការអនុម័ត · {branch}", f"{km} {number} · {who}", what[0], "",
             f"🟡 Approval needed · {branch}", f"{en} {number} by {who}", what[1]]  # fmt: skip
    if value is not None:
        lines.append(f"{'Discount' if kind == 'discount' else 'Value'}: {value} USD")
    if why_app:
        wk, we = WHY_APP[why_app]
        lines.append(f"📱 {wk} – បើកក្នុងកម្មវិធី / {we} – open in the app" + (f": {link}" if link else ""))
    return "\n".join(lines)


def approval_done(status: str, name: str, at: str, via: str) -> str:
    where = " (Telegram)" if via == "telegram" else (" (ក្នុងកម្មវិធី / in the app)" if via == "app" else "")
    return {
        "approved": f"✅ អនុម័តដោយ {name} · {at}{where} / Approved by {name} · {at}{where}",
        "rejected": f"❌ បដិសេធដោយ {name} · {at}{where} / Rejected by {name} · {at}{where}",
        "closed": f"✔️ បានបិទ · {at} / Closed · {at}",
        "expired": f"⌛ ផុតពេល · {at} / Expired · {at}",
    }[status]


def recall(branch: str, p: dict[str, Any]) -> str:
    lots = ", ".join(p.get("lots") or [])
    return (f"⛔ {branch}: recall {p.get('number')} – {p.get('sku')} lot(s) {lots} blocked, "
            f"{p.get('qty_base', 0)} on hand. Do not sell; follow the recall steps.")  # fmt: skip
