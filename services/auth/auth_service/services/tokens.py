"""Access tokens (JWT, 15 min), refresh tokens (random, 7 days, stored hashed)
and the short MFA token used between "password OK" and "6-digit code OK"."""

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import jwt

from pharmacy_shared.errors import AppError, ErrorCode

from ..config import Settings
from ..models import User


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    role: str
    branch_ids: list[UUID]
    is_pharmacist: bool
    jti: str
    issued_at_ms: int
    expires_at: int
    permissions: list[str] = field(default_factory=list)
    # True for an owner/manager who has not set up 2FA yet: only the 2FA set-up
    # screens are allowed until they do.
    mfa_setup_required: bool = False
    # The login session (refresh-token family) this token belongs to (S8b: /me/sessions)
    session_id: UUID | None = None


def create_access_token(
    user: User, settings: Settings, permissions: list[str], mfa_setup_required: bool = False,
    session_id: UUID | None = None,
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = time.time()
    expires_in = settings.jwt_access_minutes * 60
    claims = {
        "sub": str(user.id),
        "type": "access",
        "role": user.role,
        "branches": [str(b) for b in user.branch_ids],
        "ph": user.is_pharmacist,
        "perms": permissions,
        "mfa_setup": mfa_setup_required,
        "jti": uuid4().hex,
        "sid": str(session_id) if session_id else None,
        "iat": int(now),
        "iat_ms": int(now * 1000),
        "exp": int(now) + expires_in,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def _decode(token: str, settings: Settings, expected_type: str) -> dict:
    data = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp", "iat", "jti"]},
        leeway=5,
    )
    if data.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"not an {expected_type} token")
    return data


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    """Validates signature, expiry and type. Raises 401 NOT_AUTHENTICATED."""
    try:
        data = _decode(token, settings, "access")
        return AccessClaims(
            user_id=UUID(data["sub"]),
            role=str(data["role"]),
            branch_ids=[UUID(b) for b in data.get("branches", [])],
            is_pharmacist=bool(data.get("ph", False)),
            jti=str(data["jti"]),
            issued_at_ms=int(data.get("iat_ms", int(data["iat"]) * 1000)),
            expires_at=int(data["exp"]),
            permissions=[str(p) for p in data.get("perms", [])],
            mfa_setup_required=bool(data.get("mfa_setup", False)),
            session_id=UUID(data["sid"]) if data.get("sid") else None,
        )
    except (jwt.PyJWTError, KeyError, ValueError, TypeError) as exc:
        raise AppError(ErrorCode.NOT_AUTHENTICATED, "Invalid or expired token", status_code=401) from exc


def create_mfa_token(user: User, settings: Settings) -> str:
    """Proves the password was right; valid a few minutes, for one 6-digit code."""
    now = int(time.time())
    claims = {
        "sub": str(user.id),
        "type": "mfa",
        "jti": uuid4().hex,
        "iat": now,
        "exp": now + settings.mfa_token_minutes * 60,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_mfa_token(token: str, settings: Settings) -> tuple[UUID, str, int]:
    """Returns (user_id, jti, exp)."""
    try:
        data = _decode(token, settings, "mfa")
        return UUID(data["sub"]), str(data["jti"]), int(data["exp"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise AppError(
            ErrorCode.NOT_AUTHENTICATED, "Login step expired, enter your password again", status_code=401
        ) from exc


def new_refresh_token() -> tuple[str, str]:
    """Returns (token for the client, hash to store)."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
