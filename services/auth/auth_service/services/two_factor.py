"""Setting up two-factor login.

1. POST /2fa/setup  → a new secret + QR code (not active yet)
2. Scan the QR with Google Authenticator / Microsoft Authenticator / 2FAS
3. POST /2fa/enable with the 6-digit code → 2FA is on; new tokens returned
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.outbox import add_event

from ..config import Settings
from ..models import OutboxEvent, User
from . import sessions
from .audit import write_audit
from .auth import ClientInfo, IssuedTokens, _issue
from .mfa import check_code, encrypt_secret, new_secret, provisioning_uri, qr_svg_data_uri
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
            "Two-factor login is already on. Ask the owner to reset it if you lost your phone.",
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
