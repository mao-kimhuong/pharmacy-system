"""Talks to the services the way Traefik does: each person logs in at auth, /verify turns the token into the
identity headers, and calls go straight to the service on the Docker network with those headers. Back-dated calls
carry the dev clock (X-Dev-Clock + X-Service-Token; the services honour it only with APP_ENV=development)."""

import asyncio
import base64
import hashlib
import hmac
import os
import struct
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

SERVICES = ("auth", "branch", "catalog", "inventory", "stockcount", "prescription", "controlled", "sales",
            "customers", "purchasing", "reports", "notification", "document")  # fmt: skip
PREFIX = {s: f"http://{s}:8000/api/{'notifications' if s == 'notification' else 'documents' if s == 'document' else s}/v1"
          for s in SERVICES}  # fmt: skip
INTERNAL = {s: f"http://{s}:8000/internal/v1" for s in SERVICES}
TOKEN = os.environ.get("SERVICE_TOKEN", "")
# Events between services arrive a moment later: these mean "not there yet, try again"
NOT_YET = {"UNKNOWN_BRANCH", "UNKNOWN_MEDICINE", "UNKNOWN_CUSTOMER", "UNKNOWN_SUPPLIER", "UNKNOWN_PATIENT",
           "EXCHANGE_RATE_MISSING", "DOCUMENT_NOT_READY", "NOT_FOUND", "UNKNOWN_PRODUCT", "RATE_LIMITED"}  # fmt: skip


class ApiError(Exception):
    def __init__(self, status: int, body: Any, what: str) -> None:  # noqa: ANN401
        self.status, self.body, self.what = status, body, what
        code = body.get("code") if isinstance(body, dict) else None
        self.code = code
        super().__init__(f"{what} -> {status} {str(body)[:400]}")


def totp(secret: str, at: float | None = None, step_offset: int = 0) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = int((at or time.time()) // 30) + step_offset
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


@dataclass
class Person:
    key: str  # e.g. "PP1.cashier1"
    name: str
    name_km: str
    phone: str
    password: str
    role: str
    branch: str | None
    pin: str
    is_pharmacist: bool = False
    totp_secret: str | None = None
    id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


class Api:
    def __init__(self, concurrency: int = 12) -> None:
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5),
                                      limits=httpx.Limits(max_connections=64, max_keepalive_connections=32))  # fmt: skip
        self.gate = asyncio.Semaphore(concurrency)
        self.calls = 0
        self._last_totp_step: dict[str, int] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def request(self, method: str, svc: str, path: str, who: Person | None = None, body: Any = None,  # noqa: ANN401
                      *, at: datetime | None = None, key: str | None = None, params: dict | None = None,
                      ok: tuple[int, ...] = (200, 201, 204), retry_not_yet: bool = True, internal: bool = False,
                      tries: int = 24) -> Any:  # fmt: skip
        url = (INTERNAL if internal else PREFIX)[svc] + path
        headers = dict(who.headers) if who else {}
        if internal:
            headers.update({"X-Service-Token": TOKEN, "X-Service-Name": "seed"})
        if at is not None:
            headers.update({"X-Dev-Clock": at.isoformat(), "X-Service-Token": TOKEN})
        if key:
            headers["Idempotency-Key"] = key
        for attempt in range(tries):
            async with self.gate:
                self.calls += 1
                try:
                    r = await self.http.request(method, url, json=body, headers=headers, params=params)
                except httpx.TransportError:
                    await asyncio.sleep(1 + attempt)
                    continue
            data = r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r.content
            if r.status_code in ok:
                return data
            code = data.get("code") if isinstance(data, dict) else None
            if r.status_code == 429 or (retry_not_yet and code in NOT_YET) or r.status_code >= 502:
                await asyncio.sleep(min(0.4 * (attempt + 1), 3))
                continue
            raise ApiError(r.status_code, data, f"{method} {svc}{path}")
        raise ApiError(0, {"code": "GAVE_UP"}, f"{method} {svc}{path} (still not ready after {tries} tries)")

    async def get(self, svc: str, path: str, who: Person | None = None, **kw: Any) -> Any:  # noqa: ANN401
        return await self.request("GET", svc, path, who, **kw)

    async def post(self, svc: str, path: str, who: Person | None = None, body: Any = None, **kw: Any) -> Any:  # noqa: ANN401
        return await self.request("POST", svc, path, who, body if body is not None else {}, **kw)

    async def put(self, svc: str, path: str, who: Person | None = None, body: Any = None, **kw: Any) -> Any:  # noqa: ANN401
        return await self.request("PUT", svc, path, who, body, **kw)

    # ---------------------------------------------------------------- identity

    async def _code(self, secret: str) -> str:
        """A TOTP code not used before for this secret (the server refuses a replayed step)."""
        while True:
            step = int(time.time() // 30)
            if self._last_totp_step.get(secret, -1) < step:
                self._last_totp_step[secret] = step
                return totp(secret)
            await asyncio.sleep(30 - time.time() % 30 + 0.2)

    async def login(self, p: Person) -> str:
        """An access token (password, then the TOTP code if 2FA is on)."""
        r = await self.http.post(PREFIX["auth"] + "/login", json={"phone": p.phone, "password": p.password})
        if r.status_code != 200:
            raise ApiError(r.status_code, r.json(), f"login {p.key}")
        body = r.json()
        if body.get("mfa_required"):
            if not p.totp_secret:
                raise ApiError(401, {"code": "NO_TOTP_SECRET"}, f"login {p.key}: 2FA on, secret unknown")
            for attempt in range(2):  # a code used a moment ago (another run) is refused: wait for the next one
                code = await self._code(p.totp_secret)
                r = await self.http.post(PREFIX["auth"] + "/login/2fa", json={"mfa_token": body["mfa_token"], "code": code})
                if r.status_code == 200 or attempt:
                    break
                self._last_totp_step[p.totp_secret] = int(time.time() // 30)
            if r.status_code != 200:
                raise ApiError(r.status_code, r.json(), f"login/2fa {p.key}")
            body = r.json()
        return body["access_token"]

    async def identify(self, p: Person, token: str) -> None:
        """What Traefik does with the token: GET /verify → the identity headers every service trusts."""
        r = await self.http.get(PREFIX["auth"] + "/verify", headers={"Authorization": f"Bearer {token}",
                                                                      "X-Forwarded-Uri": "/api/sales/v1/x"})  # fmt: skip
        if r.status_code != 200:
            raise ApiError(r.status_code, r.text, f"verify {p.key}")
        p.headers = {k: r.headers[k] for k in ("X-User-Id", "X-Role", "X-Branch-Ids", "X-Is-Pharmacist", "X-Permissions")}
        p.id = p.headers["X-User-Id"]

    async def bearer(self, method: str, path: str, token: str, body: Any = None) -> Any:  # noqa: ANN401
        """An auth route with a fresh token (2FA setup, PIN): /verify for that path first, as Traefik does
        (a token that still needs 2FA set up only opens /me, /2fa/setup, /2fa/enable)."""
        v = await self.http.get(PREFIX["auth"] + "/verify", headers={"Authorization": f"Bearer {token}",
                                                                      "X-Forwarded-Uri": "/api/auth/v1" + path})  # fmt: skip
        if v.status_code != 200:
            raise ApiError(v.status_code, v.json() if v.content else {}, f"verify for auth{path}")
        headers = {k: v.headers[k] for k in ("X-User-Id", "X-Role", "X-Branch-Ids", "X-Is-Pharmacist", "X-Permissions")}
        r = await self.http.request(method, PREFIX["auth"] + path, json=body,
                                    headers={**headers, "Authorization": f"Bearer {token}"})  # fmt: skip
        if r.status_code >= 300:
            raise ApiError(r.status_code, r.json() if r.content else {}, f"{method} auth{path}")
        return r.json() if r.content else {}

    async def pin_token(self, p: Person, action: str, at: datetime | None = None) -> str:
        r = await self.post("auth", "/pin/verify", p, {"pin": p.pin, "action": action}, at=at)
        return r["pin_token"]

    async def witness_token(self, actor: Person, witness: Person, action: str, at: datetime | None = None) -> str:
        r = await self.post("auth", "/pin/witness", actor, {"witness_user_id": witness.id, "pin": witness.pin,
                                                            "action": action}, at=at)  # fmt: skip
        return r["witness_token"] if "witness_token" in r else r["pin_token"]


def key(*parts: Any) -> str:  # noqa: ANN401
    """A stable Idempotency-Key: running the seed twice replays instead of doing it again."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "seed-realistic:" + ":".join(str(p) for p in parts)))
