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


def money_alert(branch: str, number: str, staff: str, kind: str, lines: list[dict[str, Any]], show_cost: bool) -> str:
    """Cost only in the owner's chat (choice H)."""
    head = {"below_cost": "sold below cost", "large_discount": "large discount"}[kind]
    body = [f"💸 {branch} {number} by {staff}: {head}"]
    for x in (safe_line(x) for x in lines[:10]):
        cost = f", cost {x['cost']}" if show_cost else ""
        body.append(f"• {x['sku']} {x['name']} ×{x['qty']} {x['pack_unit']}: list {x['line_total']}, "
                    f"net {x['net']}{cost}, manual discount {x['manual_discount']}")  # fmt: skip
    return "\n".join(body)
