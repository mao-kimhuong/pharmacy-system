"""Calls between services (the sale saga: sales → inventory, sales → customers).

Internal endpoints live under /internal/v1/... (mounted by create_service_app
with `internal_router=`). Traefik routes only /api/..., so they are reachable
only on the Docker network. Every call carries:

    X-Service-Token     SERVICE_TOKEN from .env, compared in constant time
    X-Service-Name      the calling service (for logs)
    X-Acting-User-Id / X-Acting-Role / X-Acting-Branch-Id   who the call is for (User Log)
    Idempotency-Key     passed through from the user's request

Server side:  `caller: InternalCaller = Depends(internal_caller)`
Client side:  `await InternalClient(url, "sales", token).post(path, body, actor=user, ...)`

Errors from the other service come back as the same AppError (code, message,
status, details), so a saga can return OUT_OF_STOCK as it came. A service
that cannot be reached → TEMPORARILY_UNAVAILABLE (503). Only connection
errors are retried: a request that may have reached the other side is not,
because its result is unknown; the saga's idempotent compensations clean up.
"""

import asyncio
import hmac
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from fastapi import Header, Request

from . import clock
from .auth import CurrentUser
from .errors import AppError, ErrorCode

log = logging.getLogger(__name__)

TOKEN_HEADER = "X-Service-Token"


@dataclass(frozen=True)
class InternalCaller:
    service: str
    user_id: UUID | None
    role: str | None
    branch_id: UUID | None


def _uuid(value: str | None) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None


def internal_caller(
    request: Request,
    x_service_token: str | None = Header(default=None),
    x_service_name: str | None = Header(default=None),
    x_acting_user_id: str | None = Header(default=None),
    x_acting_role: str | None = Header(default=None),
    x_acting_branch_id: str | None = Header(default=None),
) -> InternalCaller:
    """Route dependency for /internal/v1 endpoints: a valid service token or 401."""
    expected: str = request.app.state.settings.service_token or ""
    given = x_service_token or ""
    if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Service token missing or wrong", status_code=401)
    return InternalCaller(
        service=x_service_name or "unknown",
        user_id=_uuid(x_acting_user_id),
        role=x_acting_role,
        branch_id=_uuid(x_acting_branch_id),
    )


class InternalClient:
    def __init__(
        self,
        base_url: str,
        service_name: str,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        connect_timeout: float = 2.0,
        read_timeout: float = 8.0,
        retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.token = token
        self.transport = transport
        self.timeout = httpx.Timeout(read_timeout, connect=connect_timeout)
        self.retries = retries

    def _headers(
        self, actor: CurrentUser | None, branch_id: UUID | None, idempotency_key: str | None
    ) -> dict:
        headers = {TOKEN_HEADER: self.token, "X-Service-Name": self.service_name}
        if actor is not None:
            headers["X-Acting-User-Id"] = str(actor.id)
            headers["X-Acting-Role"] = actor.role
        if branch_id is not None:
            headers["X-Acting-Branch-Id"] = str(branch_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        dev_at = clock.override()  # development only: the called service runs at the same (dev) time
        if dev_at is not None:
            headers[clock.HEADER] = dev_at.isoformat()
        return headers

    async def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        actor: CurrentUser | None = None,
        branch_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", path, body or {}, None, self._headers(actor, branch_id, idempotency_key))

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        actor: CurrentUser | None = None,
        branch_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Reads are safe to repeat: any transport error is retried."""
        return await self._request("GET", path, None, params, self._headers(actor, branch_id, None))

    async def _request(self, method: str, path: str, body: dict[str, Any] | None,
                       params: dict[str, Any] | None, headers: dict) -> dict[str, Any]:  # fmt: skip
        url = f"/internal/v1{path}"
        attempt = 0
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout, transport=self.transport
        ) as client:
            while True:
                try:
                    response = await client.request(method, url, json=body, params=params, headers=headers)
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    if attempt >= self.retries:
                        raise self._unavailable(str(exc)) from exc
                    attempt += 1
                    await asyncio.sleep(0.2 * 2**attempt)
                except httpx.HTTPError as exc:  # sent, but no answer: outcome unknown
                    if method == "GET" and attempt < self.retries:
                        attempt += 1
                        await asyncio.sleep(0.2 * 2**attempt)
                        continue
                    raise self._unavailable(str(exc)) from exc
        return self._result(response)

    def _unavailable(self, reason: str) -> AppError:
        service = self.base_url.split("//")[-1].split(":")[0]
        log.warning("internal call to %s failed: %s", service, reason)
        return AppError(
            ErrorCode.TEMPORARILY_UNAVAILABLE,
            f"The {service} service is not reachable; nothing was charged, try again",
            status_code=503,
            details={"service": service},
        )

    def _result(self, response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.is_success:
            return data
        try:
            code = ErrorCode(data.get("code"))
        except ValueError:
            code = ErrorCode.TEMPORARILY_UNAVAILABLE
        if response.status_code >= 500 and code != ErrorCode.TEMPORARILY_UNAVAILABLE:
            code = ErrorCode.TEMPORARILY_UNAVAILABLE
        raise AppError(
            code,
            data.get("message") or f"Internal call failed ({response.status_code})",
            status_code=response.status_code if response.status_code < 500 else 503,
            details=data.get("details") or {},
        )
