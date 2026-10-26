"""Per-user rate limit (fixed one-minute windows in Redis).

Traefik already limits per IP; this limits per staff member, so one busy branch
behind a single internet connection is not blocked by one heavy user.
Over the limit: 429 RATE_LIMITED with a Retry-After header.

If Redis is unreachable the request is allowed and a warning is logged: the POS
must keep selling during a Redis outage, and Traefik's per-IP limit still applies.
"""

import json
import logging
import time
from collections.abc import Callable, Iterable

from starlette.types import ASGIApp, Receive, Scope, Send

from .auth import USER_ID_HEADER
from .errors import ErrorCode, error_body
from .redis import RedisProvider

log = logging.getLogger(__name__)

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        redis: RedisProvider,
        service: str,
        reads_per_minute: int,
        writes_per_minute: int,
        exempt_paths: Iterable[str] = (),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self.redis = redis
        self.service = service
        self.limits = {"read": reads_per_minute, "write": writes_per_minute}
        self.exempt = frozenset(exempt_paths)
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt:
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        who = headers.get(USER_ID_HEADER)
        if who:
            who = f"user:{who}"
        else:
            forwarded = headers.get("x-forwarded-for", "")
            ip = forwarded.split(",")[0].strip() or (scope.get("client") or ("unknown",))[0]
            who = f"ip:{ip}"

        group = "read" if scope["method"] in READ_METHODS else "write"
        limit = self.limits[group]
        now = self.clock()
        window = int(now // 60)
        key = f"rl:{self.service}:{who}:{group}:{window}"

        try:
            client = self.redis.client()
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 61)
        except Exception:  # noqa: BLE001 - fail open, see module docstring
            log.warning("rate limit skipped: redis unavailable", exc_info=True)
            await self.app(scope, receive, send)
            return

        if count > limit:
            retry_after = max(1, 60 - int(now % 60))
            body = json.dumps(
                error_body(ErrorCode.RATE_LIMITED, "Too many requests", {"limit_per_minute": limit})
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", str(retry_after).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
