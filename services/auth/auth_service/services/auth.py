"""Login, refresh, logout and verify. Rules: docs/spec.md → Security & reliability.

- Wrong phone and wrong password give the same answer (INVALID_CREDENTIALS).
- 10 failed logins lock the account for 15 minutes (ACCOUNT_LOCKED, 423).
- 5 login attempts per minute per IP + phone (RATE_LIMITED, 429).
- Access token 15 min; refresh token 7 days, rotated on every use.
- Re-using a rotated refresh token revokes the whole login (family).
- Logged-out tokens and "log out everywhere" are checked in Redis by /verify.
- Owner and branch manager must use 2FA: after the password, a 6-digit code from
  the authenticator app (POST /login/2fa). Until they set it up, their token only
  opens the 2FA set-up screens (MFA_SETUP_REQUIRED on everything else).
- Wrong 2FA codes count towards the same 10-failure lockout as wrong passwords.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..config import Settings
from ..models import OutboxEvent, RefreshToken, User
from . import sessions
from .access import load_permissions, mfa_setup_required
from .audit import write_audit
from .mfa import check_code
from .passwords import hash_password, needs_rehash, verify_password
from .phone import normalize_phone
from .tokens import (
    AccessClaims,
    create_access_token,
    create_mfa_token,
    decode_access_token,
    decode_mfa_token,
    hash_refresh_token,
    new_refresh_token,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None
    user_agent: str | None


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User
    permissions: list[str]
    mfa_setup_required: bool


@dataclass(frozen=True)
class MfaChallenge:
    """Password was right; now the 6-digit code is needed."""

    mfa_token: str


# While 2FA is not set up, only these auth endpoints work.
MFA_SETUP_PATHS = ("/me", "/2fa/setup", "/2fa/enable", "/logout")


def _invalid_credentials() -> AppError:
    return AppError(ErrorCode.INVALID_CREDENTIALS, "Invalid phone or password", status_code=401)


def _session_revoked(message: str = "Session ended, please log in again") -> AppError:
    return AppError(ErrorCode.SESSION_REVOKED, message, status_code=401)


def _now() -> datetime:
    return datetime.now(UTC)


async def _check_login_rate(redis: Redis, ip: str | None, phone: str, limit: int) -> None:
    now = time.time()
    key = f"auth:login:{ip or 'unknown'}:{phone}:{int(now // 60)}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 61)
    except Exception:  # noqa: BLE001 - account lockout still protects when Redis is down
        log.warning("login rate limit skipped: redis unavailable", exc_info=True)
        return
    if count > limit:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "Too many login attempts, wait a minute",
            status_code=429,
            headers={"Retry-After": str(max(1, 60 - int(now % 60)))},
        )


async def _issue(
    session: AsyncSession, user: User, settings: Settings, client: ClientInfo, family: UUID
) -> tuple[RefreshToken, IssuedTokens]:
    raw, token_hash = new_refresh_token()
    row = RefreshToken(
        id=uuid4(),
        user_id=user.id,
        family_id=family,
        token_hash=token_hash,
        expires_at=_now() + timedelta(days=settings.jwt_refresh_days),
        ip=client.ip,
        user_agent=(client.user_agent or "")[:255] or None,
    )
    session.add(row)
    permissions = await load_permissions(session, user.role)
    setup = mfa_setup_required(user, settings)
    access, expires_in = create_access_token(user, settings, permissions, setup)
    return row, IssuedTokens(access, raw, expires_in, user, permissions, setup)


def _primary_branch(user: User) -> UUID | None:
    ids = user.branch_ids
    return ids[0] if ids else None


def _login_audit(session: AsyncSession, user: User, action: str, client: ClientInfo, **after: object) -> None:
    write_audit(
        session,
        action=action,
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        branch_id=_primary_branch(user),
        after=dict(after),
        ip=client.ip,
        only_changes=False,
    )


async def _failed_attempt(
    session: AsyncSession, user: User, settings: Settings, client: ClientInfo, reason: str
) -> AppError:
    """Count a wrong password or code; lock at the threshold. Commits."""
    user.failed_attempts += 1
    if user.failed_attempts >= settings.lockout_threshold:
        user.failed_attempts = 0
        user.locked_until = _now() + timedelta(minutes=settings.lockout_minutes)
        add_event(session, OutboxEvent, "user.locked", {"user_id": str(user.id), "ip": client.ip})
        _login_audit(session, user, "user.locked", client, reason=reason)
        await session.commit()
        return _locked(user)
    add_event(
        session,
        OutboxEvent,
        "user.login_failed",
        {"user_id": str(user.id), "ip": client.ip, "reason": reason},
    )
    _login_audit(session, user, "user.login_failed", client, reason=reason)
    await session.commit()
    if reason == "code":
        return AppError(ErrorCode.INVALID_MFA_CODE, "Wrong or expired code", status_code=401)
    return _invalid_credentials()


def _locked(user: User) -> AppError:
    assert user.locked_until is not None
    return AppError(
        ErrorCode.ACCOUNT_LOCKED,
        "Account locked after too many failed logins",
        status_code=423,
        details={"locked_until": user.locked_until.isoformat()},
    )


async def _complete_login(
    session: AsyncSession, user: User, settings: Settings, client: ClientInfo
) -> IssuedTokens:
    user.failed_attempts = 0
    user.locked_until = None
    _, tokens = await _issue(session, user, settings, client, family=uuid4())
    add_event(session, OutboxEvent, "user.logged_in", {"user_id": str(user.id), "ip": client.ip})
    _login_audit(session, user, "user.logged_in", client)
    await session.commit()
    return tokens


async def login(
    session: AsyncSession, redis: Redis, settings: Settings, phone_raw: str, password: str, client: ClientInfo
) -> IssuedTokens | MfaChallenge:
    try:
        phone = normalize_phone(phone_raw)
    except ValueError:
        verify_password(None, password)  # same timing as a real check
        raise _invalid_credentials() from None

    await _check_login_rate(redis, client.ip, phone, settings.login_attempts_per_minute)

    user = (
        await session.execute(select(User).where(User.phone == phone).with_for_update())
    ).scalar_one_or_none()

    if user is not None and user.locked_until is not None and user.locked_until > _now():
        add_event(
            session,
            OutboxEvent,
            "user.login_failed",
            {"user_id": str(user.id), "ip": client.ip, "reason": "locked"},
        )
        await session.commit()
        raise _locked(user)

    # Always run the hash check, also for an unknown phone (equal response time).
    password_ok = verify_password(user.password_hash if user else None, password)
    if user is None:
        raise _invalid_credentials()
    if not password_ok:
        raise await _failed_attempt(session, user, settings, client, "password")

    if not user.is_active:
        add_event(
            session,
            OutboxEvent,
            "user.login_failed",
            {"user_id": str(user.id), "ip": client.ip, "reason": "inactive"},
        )
        await session.commit()
        raise _invalid_credentials()

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    if user.totp_enabled:
        await session.commit()
        return MfaChallenge(create_mfa_token(user, settings))
    return await _complete_login(session, user, settings, client)


async def login_2fa(
    session: AsyncSession, redis: Redis, settings: Settings, mfa_token: str, code: str, client: ClientInfo
) -> IssuedTokens:
    user_id, jti, exp = decode_mfa_token(mfa_token, settings)
    user = (
        await session.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None or not user.is_active or not user.totp_enabled:
        raise _invalid_credentials()
    if user.locked_until is not None and user.locked_until > _now():
        raise _locked(user)
    if not check_code(user, code, settings):
        raise await _failed_attempt(session, user, settings, client, "code")
    # Each MFA token works once.
    try:
        first_use = await redis.set(
            f"auth:mfa_used:{jti}", "1", nx=True, ex=max(1, exp - int(time.time()) + 5)
        )
    except Exception:  # noqa: BLE001 - the used-code check (totp_last_step) still blocks replays
        log.warning("mfa token reuse check skipped: redis unavailable", exc_info=True)
        first_use = True
    if not first_use:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Login step already used", status_code=401)
    return await _complete_login(session, user, settings, client)


async def _revoke_family(session: AsyncSession, family_id: UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def refresh(
    session: AsyncSession, redis: Redis, settings: Settings, refresh_token: str, client: ClientInfo
) -> IssuedTokens:
    row = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Invalid refresh token", status_code=401)

    if row.revoked_at is not None:
        if row.replaced_by is not None:
            # A token that was already exchanged is being used again: it was copied.
            await _revoke_family(session, row.family_id)
            add_event(
                session,
                OutboxEvent,
                "session.reuse_detected",
                {"user_id": str(row.user_id), "family_id": str(row.family_id), "ip": client.ip},
            )
            await session.commit()
        raise _session_revoked()

    if row.expires_at <= _now():
        raise _session_revoked("Session expired, please log in again")

    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        await _revoke_family(session, row.family_id)
        await session.commit()
        raise _session_revoked()

    try:
        cutoff = await sessions.revoked_after_ms(redis, user.id)
    except Exception:  # noqa: BLE001
        log.warning("revocation check skipped: redis unavailable", exc_info=True)
        cutoff = None
    if cutoff is not None and row.created_at.timestamp() * 1000 <= cutoff:
        await _revoke_family(session, row.family_id)
        await session.commit()
        raise _session_revoked()

    new_row, tokens = await _issue(session, user, settings, client, family=row.family_id)
    row.revoked_at = _now()
    row.replaced_by = new_row.id
    await session.commit()
    return tokens


async def logout(
    session: AsyncSession,
    redis: Redis,
    claims: AccessClaims,
    refresh_token: str | None,
    all_devices: bool,
) -> None:
    await sessions.revoke_access_token(redis, claims.jti, claims.expires_at)
    if all_devices:
        await sessions.revoke_all_sessions(redis, claims.user_id)
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == claims.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
    elif refresh_token:
        row = (
            await session.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
            )
        ).scalar_one_or_none()
        if row is not None and row.user_id == claims.user_id:
            await _revoke_family(session, row.family_id)
    add_event(
        session,
        OutboxEvent,
        "user.logged_out",
        {"user_id": str(claims.user_id), "all_devices": all_devices},
    )
    write_audit(
        session,
        action="user.logged_out",
        entity_type="user",
        entity_id=claims.user_id,
        actor_id=claims.user_id,
        actor_role=claims.role,
        branch_id=claims.branch_ids[0] if claims.branch_ids else None,
        after={"all_devices": all_devices},
        only_changes=False,
    )
    await session.commit()


async def verify(
    redis: Redis, settings: Settings, authorization: str | None, forwarded_uri: str | None = None
) -> AccessClaims:
    """Used by Traefik ForwardAuth on every protected request.
    `forwarded_uri` is the path the user asked for (X-Forwarded-Uri)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Missing bearer token", status_code=401)
    claims = decode_access_token(authorization[7:].strip(), settings)
    try:
        revoked = await sessions.is_revoked(redis, claims.user_id, claims.jti, claims.issued_at_ms)
    except Exception:  # noqa: BLE001
        # Fail open on the revocation list only: signature and 15-minute expiry still
        # apply, and the POS keeps working during a Redis outage.
        log.error("revocation check skipped: redis unavailable", exc_info=True)
        revoked = False
    if revoked:
        raise _session_revoked()
    if claims.mfa_setup_required:
        path = (forwarded_uri or "").split("?", 1)[0].rstrip("/")
        allowed = {settings.api_prefix + p for p in MFA_SETUP_PATHS}
        if path not in allowed:
            raise AppError(
                ErrorCode.MFA_SETUP_REQUIRED,
                "Set up two-factor login first",
                status_code=403,
                details={"setup": f"{settings.api_prefix}/2fa/setup"},
            )
    return claims
