"""Session revocation in Redis.

- auth:revoked:{jti}           one access token, kept until it would expire anyway
- auth:revoked_after:{user_id} every access token issued before this time (ms) is refused;
                               used for "log out everywhere" and when a user is deactivated
- auth:revoked_sid:{session}   every access token of one login session (S8b: revoke a session)
"""

import time
from uuid import UUID

from redis.asyncio import Redis

REVOKED_AFTER_TTL = 60 * 60 * 24 * 8  # longer than any refresh token lives


def _jti_key(jti: str) -> str:
    return f"auth:revoked:{jti}"


def _user_key(user_id: UUID) -> str:
    return f"auth:revoked_after:{user_id}"


async def revoke_access_token(redis: Redis, jti: str, expires_at: int) -> None:
    ttl = max(1, expires_at - int(time.time()) + 5)
    await redis.set(_jti_key(jti), "1", ex=ttl)


async def revoke_all_sessions(redis: Redis, user_id: UUID) -> int:
    """Refuse every access token issued until now. Returns the cut-off in ms."""
    cutoff_ms = int(time.time() * 1000)
    await redis.set(_user_key(user_id), str(cutoff_ms), ex=REVOKED_AFTER_TTL)
    return cutoff_ms


async def revoke_session(redis: Redis, session_id: UUID, ttl_seconds: int) -> None:
    """Refuse the access tokens of one login session (they live at most ttl_seconds)."""
    await redis.set(f"auth:revoked_sid:{session_id}", "1", ex=max(1, ttl_seconds + 5))


async def is_revoked(
    redis: Redis, user_id: UUID, jti: str, issued_at_ms: int, session_id: UUID | None = None
) -> bool:
    keys = [_jti_key(jti), _user_key(user_id)] + ([f"auth:revoked_sid:{session_id}"] if session_id else [])
    revoked_jti, cutoff, *sid = await redis.mget(*keys)
    if revoked_jti is not None or (sid and sid[0] is not None):
        return True
    return cutoff is not None and issued_at_ms <= int(cutoff)


async def revoked_after_ms(redis: Redis, user_id: UUID) -> int | None:
    value = await redis.get(_user_key(user_id))
    return int(value) if value is not None else None
