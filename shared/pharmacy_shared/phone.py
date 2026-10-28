import re

_STRIP = re.compile(r"[\s\-().]")
_VALID = re.compile(r"^\+?\d{8,15}$")


def normalize_phone(raw: str) -> str:
    """Store and compare phones in one form: Cambodian numbers as 0XXXXXXXX.

    "+855 12 345 678", "855-12-345-678" and "012 345 678" all become "012345678".
    Raises ValueError for anything that is not a phone number.
    """
    phone = _STRIP.sub("", raw or "")
    if phone.startswith("+855"):
        phone = "0" + phone[4:]
    elif phone.startswith("855") and len(phone) >= 11:
        phone = "0" + phone[3:]
    if not _VALID.match(phone):
        raise ValueError("invalid phone number")
    return phone
