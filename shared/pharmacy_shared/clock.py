"""Business dates are Cambodian dates (Asia/Phnom_Penh, UTC+7), not UTC: a
batch expiring on 2026-10-31 is still sellable until midnight in Phnom Penh,
and document numbers use the local year. Tests monkeypatch `today`.

Dev clock (make seed-realistic only): a request carrying `X-Dev-Clock: <ISO time>` AND a valid
`X-Service-Token` runs as if it were that time – `now()`, `today()`, database `created_at` defaults
(pharmacy_shared.db) and the internal calls it makes (pharmacy_shared.internal forwards the header).
The middleware that reads the header is only added when APP_ENV=development and ENVIRONMENT is not
production (`dev_clock_allowed`); everywhere else the header is ignored and nothing here is ever set.
"""

import os
import time
from contextvars import ContextVar, Token
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Phnom_Penh")
HEADER = "X-Dev-Clock"

# (the time asked for, monotonic seconds when it was set): time keeps moving inside the request
_override: ContextVar[tuple[datetime, float] | None] = ContextVar("pharmacy_dev_clock", default=None)


def now() -> datetime:
    o = _override.get()
    if o is not None:
        return o[0] + timedelta(seconds=time.monotonic() - o[1])
    return datetime.now(UTC)


def today() -> date:
    return now().astimezone(TIMEZONE).date()


def override() -> datetime | None:
    """The dev clock's current time, or None (always None outside development)."""
    return now() if _override.get() is not None else None


def dev_clock_allowed(settings: Any) -> bool:  # noqa: ANN401 – BaseServiceSettings
    return os.environ.get("APP_ENV") == "development" and not settings.is_production


def set_override(at: datetime) -> Token:
    if at.tzinfo is None:
        raise ValueError("the dev clock needs a time zone")
    return _override.set((at.astimezone(UTC), time.monotonic()))


def reset_override(token: Token) -> None:
    _override.reset(token)


class DevClockMiddleware:
    """Development only (create_service_app adds it when dev_clock_allowed). Needs the service token too,
    so a browser on a development stack cannot move a sale in time."""

    def __init__(self, app: Any, service_token: str) -> None:  # noqa: ANN401
        self.app, self.service_token = app, service_token.encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        raw = headers.get(HEADER.lower().encode())
        token = headers.get(b"x-service-token", b"")
        import hmac

        if not raw or not self.service_token or not hmac.compare_digest(token, self.service_token):
            return await self.app(scope, receive, send)
        try:
            at = datetime.fromisoformat(raw.decode())
            handle = set_override(at)
        except ValueError:
            return await self.app(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_override(handle)
