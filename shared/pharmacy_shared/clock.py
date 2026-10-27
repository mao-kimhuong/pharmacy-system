"""Business dates are Cambodian dates (Asia/Phnom_Penh, UTC+7), not UTC: a
batch expiring on 2026-10-31 is still sellable until midnight in Phnom Penh,
and document numbers use the local year. Tests monkeypatch `today`."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Phnom_Penh")


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return datetime.now(TIMEZONE).date()
