"""Texts for customer, supplier and bot chats, in Khmer (km) and English (en).

Privacy (T2): templates take ONLY these values – document numbers (invoice, order,
return, Rx, PO), amounts, dates, branch names, and the medicine name only when the
customer chose "show medicine names". Rx notes, allergies, chronic conditions,
diagnoses, doctor names, patient names and IDs are never passed in, so they can
never reach Telegram (tests/test_customer_telegram.py renders every template and
every event handler with all of them planted and scans the result).
Customer names are not used either: a forwarded message names nobody.
"""

from datetime import date
from decimal import Decimal
from typing import Any

TOPIC_LABELS = {
    "receipts": ("បង្កាន់ដៃ", "Receipts"),
    "reminders": ("ការរំលឹកយកថ្នាំ", "Refill reminders"),
    "balance": ("សមតុល្យជំពាក់", "Account balance"),
    "orders": ("ការកម្ម៉ង់", "Orders"),
    "show_medicine_names": ("បង្ហាញឈ្មោះថ្នាំ", "Show medicine names"),
    "marketing": ("ប្រូម៉ូសិន", "Promotions"),
}


def _d(day: date | str | None) -> str:
    if not day:
        return ""
    value = date.fromisoformat(day) if isinstance(day, str) else day
    return value.strftime("%d/%m/%Y")


def _usd(value: Any) -> str:
    return f"{Decimal(str(value or 0)):,.2f}"


def _riel(value: Any) -> str:
    return f"{int(value or 0):,}"


def branch_name(branch: dict[str, Any] | None, lang: str) -> str:
    b = branch or {}
    return (b.get("name_km") if lang == "km" else None) or b.get("name_en") or b.get("code") or ""


# ------------------------------------------------------------------ customer messages


def receipt(lang: str, branch: str, number: str, total_usd: Any, total_khr: Any) -> str:
    if lang == "km":
        return f"🧾 {branch}\nបង្កាន់ដៃ {number}: {_usd(total_usd)} USD ({_riel(total_khr)} ៛)\nសូមអរគុណ!"
    return f"🧾 {branch}\nReceipt {number}: {_usd(total_usd)} USD ({_riel(total_khr)} KHR)\nThank you!"


def refill(lang: str, branch: str, rx_number: str, runs_out_on: date | str, refills_left: bool,
           medicine: str | None) -> str:  # fmt: skip
    """medicine: only when the customer chose show_medicine_names (else None)."""
    if lang == "km":
        what = f"ថ្នាំ {medicine} " if medicine else "ថ្នាំ"
        next_step = (f"អ្នកអាចមកយកថ្នាំបន្តនៅ {branch}។" if refills_left
                     else f"សូមយកវេជ្ជបញ្ជាថ្មីមក {branch}។")  # fmt: skip
        return f"💊 {what}តាមវេជ្ជបញ្ជា {rx_number} នឹងអស់ប្រហែលថ្ងៃទី {_d(runs_out_on)}។\n{next_step}"
    what = f"Your {medicine}" if medicine else "Your medicine"
    next_step = (f"You can collect a refill at {branch}." if refills_left
                 else f"Please bring a new prescription to {branch}.")  # fmt: skip
    return f"💊 {what} from prescription {rx_number} runs out around {_d(runs_out_on)}.\n{next_step}"


def order_ready(lang: str, branch: str, number: str, remaining_usd: Any) -> str:
    left = Decimal(str(remaining_usd or 0))
    if lang == "km":
        pay = f"ប្រាក់ត្រូវបង់ពេលមកយក: {_usd(left)} USD។" if left > 0 else "បានបង់គ្រប់ហើយ។"
        return f"📦 ការកម្ម៉ង់ {number} រួចរាល់ហើយ សូមមកយកនៅ {branch}។\n{pay}"
    pay = f"To pay at pickup: {_usd(left)} USD." if left > 0 else "Fully paid."
    return f"📦 Order {number} is ready for pickup at {branch}.\n{pay}"


ORDER_STATUS = {
    "ordered": ("បានទទួលការកម្ម៉ង់", "confirmed"),
    "partly_fulfilled": ("បានប្រគល់មួយផ្នែក", "partly delivered"),
    "fulfilled": ("បានប្រគល់គ្រប់", "delivered"),
    "cancelled": ("បានលុបចោល", "cancelled"),
    "closed": ("បានបិទ", "closed"),
}


def order_status(lang: str, branch: str, number: str, status: str) -> str:
    km, en = ORDER_STATUS.get(status, (status, status))
    if lang == "km":
        return f"📋 {branch}: ការកម្ម៉ង់ {number} – {km}។"
    return f"📋 {branch}: order {number} – {en}."


def balance(lang: str, balance_usd: Any, overdue_usd: Any, overdue_since: date | str | None, overdue: bool,
            pay_link: str | None = None) -> str:  # fmt: skip
    due = Decimal(str(overdue_usd or 0))
    if lang == "km":
        head = "⏰ ប្រាក់ជំពាក់ហួសកាលកំណត់" if overdue else "📄 សមតុល្យគណនីប្រចាំខែ"
        lines = [head, f"សមតុល្យជំពាក់: {_usd(balance_usd)} USD"]
        if due > 0:
            lines.append(f"ហួសកាលកំណត់: {_usd(due)} USD (តាំងពី {_d(overdue_since)})")
        lines.append("របាយការណ៍គណនីភ្ជាប់មកជាមួយ។ " + (f"បង់តាម PayWay: {pay_link}" if pay_link
                                                       else "អាចបង់ប្រាក់នៅសាខាណាមួយរបស់យើង។"))  # fmt: skip
        return "\n".join(lines)
    head = "⏰ Payment overdue" if overdue else "📄 Monthly account balance"
    lines = [head, f"Balance: {_usd(balance_usd)} USD"]
    if due > 0:
        lines.append(f"Overdue: {_usd(due)} USD (since {_d(overdue_since)})")
    lines.append("Your statement is attached. " + (f"Pay with PayWay: {pay_link}" if pay_link
                                                    else "You can pay at any of our branches."))  # fmt: skip
    return "\n".join(lines)


def deposit_taken(lang: str, branch: str, order_number: str, amount_usd: Any) -> str:
    if lang == "km":
        return f"💵 {branch}: បានទទួលប្រាក់កក់ {_usd(amount_usd)} USD សម្រាប់ការកម្ម៉ង់ {order_number}។ សូមអរគុណ!"
    return f"💵 {branch}: deposit of {_usd(amount_usd)} USD received for order {order_number}. Thank you!"


def deposit_refunded(lang: str, branch: str, order_number: str, amount_usd: Any) -> str:
    if lang == "km":
        return f"↩️ {branch}: បានសងប្រាក់កក់ {_usd(amount_usd)} USD វិញ សម្រាប់ការកម្ម៉ង់ {order_number}។"
    return f"↩️ {branch}: deposit of {_usd(amount_usd)} USD refunded for order {order_number}."


def deposit_credit(lang: str, branch: str, order_number: str, amount_usd: Any) -> str:
    if lang == "km":
        return (f"💳 {branch}: ប្រាក់កក់ {_usd(amount_usd)} USD នៃការកម្ម៉ង់ {order_number} "
                "ត្រូវបានរក្សាទុកជាឥណទានសម្រាប់ការទិញលើកក្រោយ។")  # fmt: skip
    return f"💳 {branch}: the deposit of {_usd(amount_usd)} USD from order {order_number} is kept as credit for your next purchase."


REFUND_METHOD = {"cash": ("ជាសាច់ប្រាក់", "in cash"), "credit": ("ជាឥណទានក្នុងគណនី", "as credit on your account"),
                 "khqr": ("តាម KHQR", "by KHQR")}  # fmt: skip


def return_refund(lang: str, branch: str, return_number: str, amount_usd: Any, method: str) -> str:
    km, en = REFUND_METHOD.get(method, ("", ""))
    if lang == "km":
        return f"↩️ {branch}: បានសងប្រាក់ {_usd(amount_usd)} USD {km} សម្រាប់ការប្តូរយកវិញ {return_number}។".replace("  ", " ")
    return f"↩️ {branch}: {_usd(amount_usd)} USD refunded {en} for return {return_number}.".replace("  ", " ")


def marketing(lang: str, text_km: str, text_en: str) -> str:
    if lang == "km":
        return f"🎁 {text_km}\n\nមិនចង់ទទួលប្រូម៉ូសិន? ផ្ញើ /settings"
    return f"🎁 {text_en}\n\nNo more promotions? Send /settings"


def supplier_po(lang: str, number: str, branch: str, expected_on: date | str | None) -> str:
    when = f" · {_d(expected_on)}" if expected_on else ""
    if lang == "km":
        return f"🛒 ការបញ្ជាទិញ {number} ពី {branch}{when}។ សូមចុច \"បានទទួល / បញ្ជាក់\" នៅពេលអ្នកបានឃើញ។"
    return f"🛒 Purchase order {number} from {branch}{when}. Please tap \"Received / Confirmed\" once you have seen it."


# ------------------------------------------------------------------ bot replies (before we know the language: both)


def both(km: str, en: str) -> str:
    return f"{km}\n\n{en}"


HELLO = both("សួស្តី! នេះជាបូតរបស់ឱសថស្ថាន។ ដើម្បីភ្ជាប់ សូមស្កេន QR នៅលើបង្កាន់ដៃ ឬសួរបុគ្គលិក។",
             "Hello! This is the pharmacy's bot. To link your account, scan the QR code on your receipt or ask our staff.")  # fmt: skip
TOKEN_BAD = both("តំណនេះមិនអាចប្រើបានទៀតទេ (បានប្រើរួច ឬផុតកំណត់)។ សូមសួរបុគ្គលិកដើម្បីទទួលតំណថ្មី។",
                 "This link can no longer be used (already used or expired). Ask our staff for a new one.")  # fmt: skip
SHARE_PHONE = both("ដើម្បីការពារគណនីរបស់អ្នក សូមចុចប៊ូតុងខាងក្រោម ដើម្បីចែករំលែកលេខទូរស័ព្ទរបស់អ្នក។",
                   "To protect your account, tap the button below to share your phone number.")  # fmt: skip
SHARE_BUTTON = "📱 ចែករំលែកលេខទូរស័ព្ទ / Share phone number"
PHONE_MISMATCH = both("លេខទូរស័ព្ទនេះមិនត្រូវនឹងគណនីរបស់យើងទេ។ សូមសួរបុគ្គលិកដើម្បីភ្ជាប់នៅតុបញ្ជរ។",
                      "This phone number does not match our records. Ask our staff to link you at the counter.")  # fmt: skip
NOT_YOUR_CONTACT = both("សូមចែករំលែកលេខទូរស័ព្ទរបស់អ្នកផ្ទាល់ (ប៊ូតុងខាងក្រោម)។",
                        "Please share your own phone number (the button below).")  # fmt: skip
GROUP_NO_LINK = both("ការភ្ជាប់គណនីធ្វើបានតែក្នុងការជជែកផ្ទាល់ជាមួយបូតប៉ុណ្ណោះ។",
                     "Accounts can only be linked in a private chat with the bot.")  # fmt: skip
STOPPED = both("អ្នកនឹងមិនទទួលសារពីយើងទៀតទេ។ ដើម្បីភ្ជាប់ម្តងទៀត សូមស្កេន QR ថ្មី។",
               "You will get no more messages from us. To link again, scan a new QR code.")  # fmt: skip
NOT_LINKED = both("ការជជែកនេះមិនទាន់បានភ្ជាប់ទេ។", "This chat is not linked.")


def linked(lang: str, kind: str = "customer", label: str = "") -> str:
    if kind == "staff":
        return both(f"✅ បានភ្ជាប់គណនីបុគ្គលិក{(' ' + label) if label else ''}។ ផ្ញើ /help ដើម្បីមើលពាក្យបញ្ជា។",
                    f"✅ Staff account linked{(' (' + label + ')') if label else ''}. Send /help for the commands.")  # fmt: skip
    if kind == "supplier":
        return both(f"✅ បានភ្ជាប់{(' ' + label) if label else ''}។ អ្នកនឹងទទួលការបញ្ជាទិញនៅទីនេះ។",
                    f"✅ Linked{(' (' + label + ')') if label else ''}. You will get our purchase orders here.")  # fmt: skip
    if lang == "km":
        return ("✅ បានភ្ជាប់រួចរាល់! អ្នកនឹងទទួលបង្កាន់ដៃ ការរំលឹក និងព័ត៌មានគណនីនៅទីនេះ។\n"
                "ផ្ញើ /settings ដើម្បីជ្រើសរើស ឬ /stop ដើម្បីបញ្ឈប់។")  # fmt: skip
    return ("✅ Linked! You will get receipts, reminders and account news here.\n"
            "Send /settings to choose, or /stop to stop.")  # fmt: skip


def settings_text(lang: str) -> str:
    return "ជ្រើសរើសសារដែលអ្នកចង់ទទួល (ចុចដើម្បីបើក/បិទ):" if lang == "km" else "Choose what you get (tap to turn on/off):"


def settings_markup(lang: str, consents: dict[str, bool]) -> dict[str, Any]:
    rows = []
    for topic, (km, en) in TOPIC_LABELS.items():
        on = consents.get(topic, False)
        rows.append([{"text": f"{'✅' if on else '⬜'} {km if lang == 'km' else en}", "callback_data": f"cs:{topic}"}])
    rows.append([{"text": "🛑 /stop", "callback_data": "cs:stop"}])
    return {"inline_keyboard": rows}


def customer_help(lang: str) -> str:
    if lang == "km":
        return "/settings – ជ្រើសរើសសារ\n/stop – បញ្ឈប់ និងផ្តាច់ការភ្ជាប់\n/help – ជំនួយ"
    return "/settings – choose your messages\n/stop – stop and unlink\n/help – this help"
