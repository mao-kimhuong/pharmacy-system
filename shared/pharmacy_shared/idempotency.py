"""Idempotency-Key handling.

Any POST/PUT/PATCH/DELETE that carries an `Idempotency-Key` header is run once
per (service, user, key). A retry with the same key and the same request returns
the saved response with `Idempotent-Replayed: true`, so a flaky connection can
never sell twice or record a payment twice. Responses are kept 24 hours.

- Same key, different request  -> 422 IDEMPOTENCY_KEY_REUSED
- Same key while the first is still running -> 409 IDEMPOTENCY_IN_PROGRESS
- 5xx responses and crashes are not saved, so the client can retry.

Routes that change money or stock make the header mandatory with the
`require_idempotency_key` dependency.
"""

import base64
import hashlib
import json
import logging
import re
from typing import Any

from fastapi import Header
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth import USER_ID_HEADER
from .errors import AppError, ErrorCode, error_body
from .redis import RedisProvider

log = logging.getLogger(__name__)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")
HEADER = "idempotency-key"


def require_idempotency_key(idempotency_key: str | None = Header(default=None)) -> str:
    """Dependency for routes that change money or stock."""
    if not idempotency_key:
        raise AppError(
            ErrorCode.IDEMPOTENCY_KEY_REQUIRED, "Idempotency-Key header is required", status_code=400
        )
    return idempotency_key


class IdempotencyMiddleware:
    def __init__(self, app: ASGIApp, *, redis: RedisProvider, service: str, ttl_seconds: int) -> None:
        self.app = app
        self.redis = redis
        self.service = service
        self.ttl = ttl_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in WRITE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        idem_key = headers.get(HEADER)
        if idem_key is None:
            await self.app(scope, receive, send)
            return
        if not KEY_PATTERN.match(idem_key):
            await _send_json(
                send,
                400,
                error_body(
                    ErrorCode.IDEMPOTENCY_KEY_INVALID,
                    "Idempotency-Key must be 8-128 letters, digits, - _ : .",
                ),
            )
            return

        body = await _read_body(receive)
        fingerprint = hashlib.sha256(
            scope["method"].encode() + b" " + scope["path"].encode() + b"\n" + body
        ).hexdigest()
        who = headers.get(USER_ID_HEADER, "anonymous")
        redis_key = f"idem:{self.service}:{who}:{idem_key}"

        try:
            client = self.redis.client()
            claimed = await client.set(
                redis_key, json.dumps({"state": "running", "fp": fingerprint}), nx=True, ex=self.ttl
            )
            existing = None if claimed else await client.get(redis_key)
        except Exception:  # noqa: BLE001
            # Without Redis we cannot guarantee "once"; refuse rather than risk a double sale.
            log.error("idempotency store unavailable", exc_info=True)
            await _send_json(
                send, 503, error_body(ErrorCode.TEMPORARILY_UNAVAILABLE, "Please retry in a moment")
            )
            return

        if not claimed:
            await self._answer_existing(send, existing, fingerprint)
            return

        await self._run_and_store(scope, body, receive, send, client, redis_key, fingerprint)

    async def _answer_existing(self, send: Send, raw: str | None, fingerprint: str) -> None:
        record: dict[str, Any] = json.loads(raw) if raw else {}
        if record.get("fp") != fingerprint:
            await _send_json(
                send,
                422,
                error_body(
                    ErrorCode.IDEMPOTENCY_KEY_REUSED,
                    "This Idempotency-Key was already used for a different request",
                ),
            )
            return
        if record.get("state") != "done":
            await _send_json(
                send,
                409,
                error_body(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "The first request is still running"),
            )
            return
        headers = [(k.encode(), v.encode()) for k, v in record["headers"]]
        headers.append((b"idempotent-replayed", b"true"))
        await send({"type": "http.response.start", "status": record["status"], "headers": headers})
        await send({"type": "http.response.body", "body": base64.b64decode(record["body"])})

    async def _run_and_store(
        self,
        scope: Scope,
        body: bytes,
        receive: Receive,
        send: Send,
        client: Any,
        redis_key: str,
        fingerprint: str,
    ) -> None:
        body_sent = False

        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        status = 500
        resp_headers: list[tuple[str, str]] = []
        chunks: list[bytes] = []

        async def capture_send(message: Message) -> None:
            nonlocal status, resp_headers
            if message["type"] == "http.response.start":
                status = message["status"]
                resp_headers = [
                    (k.decode(), v.decode())
                    for k, v in message.get("headers", [])
                    if k.decode().lower() in ("content-type", "location", "retry-after")
                ]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_receive, capture_send)
        except Exception:
            await _safe_delete(client, redis_key)
            raise

        if status >= 500:
            await _safe_delete(client, redis_key)
            return
        record = {
            "state": "done",
            "fp": fingerprint,
            "status": status,
            "headers": resp_headers,
            "body": base64.b64encode(b"".join(chunks)).decode(),
        }
        try:
            await client.set(redis_key, json.dumps(record), ex=self.ttl)
        except Exception:  # noqa: BLE001
            log.error("could not save idempotent response", exc_info=True)


async def _read_body(receive: Receive) -> bytes:
    parts: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        parts.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(parts)


async def _send_json(send: Send, status: int, content: dict[str, Any]) -> None:
    await send(
        {"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]}
    )
    await send({"type": "http.response.body", "body": json.dumps(content).encode()})


async def _safe_delete(client: Any, key: str) -> None:
    try:
        await client.delete(key)
    except Exception:  # noqa: BLE001
        log.error("could not clear idempotency key %s", key, exc_info=True)
