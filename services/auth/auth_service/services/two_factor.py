"""Two-factor login: set-up, turning it off, a new key, new backup codes.

1. POST /2fa/setup  → a new secret + QR code (not active yet)
2. Scan the QR with Google Authenticator / Microsoft Authenticator / 2FAS
3. POST /2fa/enable with the 6-digit code → 2FA is on; new tokens returned

Turning it off (`disable`) and asking for a new key or new backup codes need the password AND a
code or backup code, under the login lockout (wrong ones count, a locked account is refused).
Roles that must use 2FA cannot turn it off (MFA_REQUIRED_FOR_ROLE): they take a new key in two
steps, and the old key keeps working until a code from the new one is confirmed.
Off or reset: the user's other sessions end, a User Log entry is written, and an event goes to
the owner's Telegram chat (no secrets in it).
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..config import Settings
from ..models import OutboxEvent, RefreshToken, User
from . import backup_codes, sessions
from .audit import write_audit
from .auth import (
    ClientInfo,
    IssuedTokens,
    _failed_attempt,
    _issue,
    _locked,
    _login_audit,
    _now,
    _revoke_family,
)
from .mfa import check_code, decrypt_secret, encrypt_secret, new_secret, provisioning_uri, qr_svg_data_uri
from .passwords import verify_password
from .tokens import AccessClaims


@dataclass(frozen=True)
class SetupInfo:
    secret: str
    otpauth_uri: str
    qr_svg: str


async def _user(session: AsyncSession, user_id: UUID) -> User:
    user = (
        await session.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Not authenticated", status_code=401)
    return user


async def start_setup(session: AsyncSession, settings: Settings, user_id: UUID) -> SetupInfo:
    user = await _user(session, user_id)
    if user.totp_enabled:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Two-factor login is already on. Lost your phone? Use a backup code, or ask the owner to reset it.",
            status_code=409,
        )
    secret = new_secret()
    user.totp_secret_enc = encrypt_secret(secret, settings)
    user.totp_last_step = None
    await session.commit()
    uri = provisioning_uri(secret, user, settings)
    return SetupInfo(secret=secret, otpauth_uri=uri, qr_svg=qr_svg_data_uri(uri))


async def enable(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    claims: AccessClaims,
    code: str,
    client: ClientInfo,
) -> IssuedTokens:
    user = await _user(session, claims.user_id)
    if user.totp_enabled:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Two-factor login is already on", status_code=409)
    if not user.totp_secret_enc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Start the set-up first", status_code=409)
    if not check_code(user, code, settings):
        raise AppError(ErrorCode.INVALID_MFA_CODE, "Wrong or expired code", status_code=401)
    user.totp_enabled = True
    # The set-up token cannot be used any more; the new tokens open everything.
    await sessions.revoke_access_token(redis, claims.jti, claims.expires_at)
    if claims.session_id is not None:  # the new tokens replace this login session
        await _revoke_family(session, claims.session_id)
    _, tokens = await _issue(session, user, settings, client, family=uuid4())
    add_event(session, OutboxEvent, "user.2fa_enabled", {"user_id": str(user.id)})
    write_audit(
        session,
        action="user.2fa_enabled",
        entity_type="user",
        entity_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        branch_id=user.branch_ids[0] if user.branch_ids else None,
        before={"totp_enabled": False},
        after={"totp_enabled": True},
        ip=client.ip,
        only_changes=False,
    )
    await session.commit()
    return tokens


async def step_up(
    session: AsyncSession, user: User, settings: Settings, password: str, code: str | None,
    backup_code: str | None, client: ClientInfo,
) -> None:  # fmt: skip
    """Password and a code or backup code, with the same lockout as login."""
    if user.locked_until is not None and user.locked_until > _now():
        raise _locked(user)
    if not user.totp_enabled:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Two-factor login is off", status_code=409)
    if not verify_password(user.password_hash, password):
        raise await _failed_attempt(session, user, settings, client, "password")
    if backup_code:
        if not await backup_codes.consume(session, user, backup_code):
            raise await _failed_attempt(session, user, settings, client, "backup code")
        _login_audit(session, user, "user.backup_code_used", client, left=await backup_codes.left(session, user.id))
    elif not code or not check_code(user, code, settings):
        raise await _failed_attempt(session, user, settings, client, "code")
    user.failed_attempts = 0


async def end_other_sessions(
    session: AsyncSession, redis: Redis, settings: Settings, user_id: UUID, keep: UUID | None
) -> None:
    """Every login session of the user except `keep`: refresh tokens and access tokens, at once."""
    families = (await session.execute(select(func.distinct(RefreshToken.family_id)).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None), RefreshToken.family_id != keep
    ))).scalars().all() if keep else None  # fmt: skip
    if keep is None:  # no session to keep: everything issued until now
        await sessions.revoke_all_sessions(redis, user_id)
    query = update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
    await session.execute((query.where(RefreshToken.family_id != keep) if keep else query).values(revoked_at=_now()))
    for family in families or []:
        await sessions.revoke_session(redis, family, settings.jwt_access_minutes * 60)


def clear_secrets(user: User) -> None:
    user.totp_secret_enc = user.totp_pending_secret_enc = None
    user.totp_enabled = False
    user.totp_last_step = None


def security_event(session: AsyncSession, user: User, event: str, by: str) -> None:
    """To the owner's Telegram chat (notification). `by`: self, owner or server. No secrets."""
    add_event(session, OutboxEvent, event, {"user_id": str(user.id), "by": by, "occurred_at": _now().isoformat()})


def _audit(session: AsyncSession, user: User, action: str, client: ClientInfo, **after: object) -> None:
    write_audit(session, action=action, entity_type="user", entity_id=user.id, actor_id=user.id, actor_role=user.role,
                branch_id=user.branch_ids[0] if user.branch_ids else None, after=dict(after), ip=client.ip,
                only_changes=False)  # fmt: skip


async def disable(
    session: AsyncSession, redis: Redis, settings: Settings, claims: AccessClaims, password: str, code: str | None,
    backup_code: str | None, client: ClientInfo,
) -> None:  # fmt: skip
    user = await _user(session, claims.user_id)
    if user.role in settings.roles_requiring_2fa:
        raise AppError(ErrorCode.MFA_REQUIRED_FOR_ROLE, "Your role must use two-factor login; you can only reset it",
                       status_code=403)  # fmt: skip
    await step_up(session, user, settings, password, code, backup_code, client)
    clear_secrets(user)
    await backup_codes.retire(session, user.id)
    await end_other_sessions(session, redis, settings, user.id, claims.session_id)
    security_event(session, user, "user.2fa_disabled", "self")
    _audit(session, user, "user.2fa_disabled", client, totp_enabled=False)
    await session.commit()


async def start_reset(
    session: AsyncSession, settings: Settings, claims: AccessClaims, password: str, code: str | None,
    backup_code: str | None, client: ClientInfo,
) -> SetupInfo:  # fmt: skip
    """Step 1 of a new key: it waits in totp_pending_secret_enc; the old key keeps working."""
    user = await _user(session, claims.user_id)
    await step_up(session, user, settings, password, code, backup_code, client)
    secret = new_secret()
    user.totp_pending_secret_enc = encrypt_secret(secret, settings)
    await session.commit()
    uri = provisioning_uri(secret, user, settings)
    return SetupInfo(secret=secret, otpauth_uri=uri, qr_svg=qr_svg_data_uri(uri))


async def confirm_reset(
    session: AsyncSession, redis: Redis, settings: Settings, claims: AccessClaims, code: str, client: ClientInfo
) -> list[str]:
    """Step 2: a code from the new key makes it live. Returns the 10 new backup codes."""
    user = await _user(session, claims.user_id)
    if user.locked_until is not None and user.locked_until > _now():
        raise _locked(user)
    pending = user.totp_pending_secret_enc
    if not pending or decrypt_secret(pending, settings) is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Start the reset first", status_code=409)
    old_step, user.totp_last_step = user.totp_last_step, None  # the old key's steps say nothing about the new one
    if not check_code(user, code, settings, secret_enc=pending):
        user.totp_last_step = old_step  # the old key stays live, with its replay guard
        raise await _failed_attempt(session, user, settings, client, "code")
    user.totp_secret_enc, user.totp_pending_secret_enc, user.failed_attempts = pending, None, 0
    codes = await backup_codes.regenerate(session, user)
    await end_other_sessions(session, redis, settings, user.id, claims.session_id)
    security_event(session, user, "user.2fa_reset", "self")
    _audit(session, user, "user.2fa_reset", client, by="self")
    await session.commit()
    return codes


async def new_backup_codes(
    session: AsyncSession, settings: Settings, claims: AccessClaims, password: str, code: str | None,
    backup_code: str | None, client: ClientInfo,
) -> list[str]:  # fmt: skip
    user = await _user(session, claims.user_id)
    await step_up(session, user, settings, password, code, backup_code, client)
    codes = await backup_codes.regenerate(session, user)
    _audit(session, user, "user.backup_codes_regenerated", client, codes=len(codes))
    await session.commit()
    return codes
