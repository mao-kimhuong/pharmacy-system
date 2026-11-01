"""Your login sessions (S8b). A session is one refresh-token family (one login; each
refresh replaces the token in the family). Listed newest first, the one this
request comes from marked `current`. Revoking one ends it at once: its refresh
tokens are revoked and its access tokens refused (Redis); revoking the current
one = logging out. Only your own sessions. User Log user.session_revoked."""


from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared import clock
from pharmacy_shared.errors import AppError, ErrorCode

from ..config import Settings
from ..models import RefreshToken, User
from . import sessions
from .audit import write_audit
from .tokens import AccessClaims


async def list_sessions(session: AsyncSession, claims: AccessClaims) -> list[dict[str, Any]]:
    now = clock.now()
    fam = (select(RefreshToken.family_id, func.min(RefreshToken.created_at).label("started_at"),
                  func.max(RefreshToken.created_at).label("last_used_at"))
           .where(RefreshToken.user_id == claims.user_id).group_by(RefreshToken.family_id).subquery())  # fmt: skip
    rows = (await session.execute(
        select(RefreshToken, fam.c.started_at).join(fam, (fam.c.family_id == RefreshToken.family_id)
                                                    & (fam.c.last_used_at == RefreshToken.created_at))
        .where(RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now)
        .order_by(RefreshToken.created_at.desc()))).all()  # fmt: skip
    return [{"id": t.family_id, "started_at": started, "last_used_at": t.created_at, "expires_at": t.expires_at,
             "ip": t.ip, "user_agent": t.user_agent, "current": t.family_id == claims.session_id}
            for t, started in rows]  # fmt: skip


async def revoke(session: AsyncSession, redis: Redis, settings: Settings, claims: AccessClaims, family_id: UUID,
                 ip: str | None) -> None:  # fmt: skip
    owned = (await session.execute(select(func.count()).select_from(RefreshToken).where(
        RefreshToken.family_id == family_id, RefreshToken.user_id == claims.user_id))).scalar_one()  # fmt: skip
    if not owned:
        raise AppError(ErrorCode.NOT_FOUND, "Session not found", status_code=404)
    await session.execute(update(RefreshToken).where(RefreshToken.family_id == family_id,
                                                     RefreshToken.revoked_at.is_(None)).values(revoked_at=clock.now()))  # fmt: skip
    await sessions.revoke_session(redis, family_id, settings.jwt_access_minutes * 60)
    user = await session.get(User, claims.user_id)
    write_audit(session, action="user.session_revoked", entity_type="user", entity_id=claims.user_id,
                actor_id=claims.user_id, actor_role=claims.role,
                branch_id=user.branch_ids[0] if user and user.branch_ids else None,
                after={"session": str(family_id), "current": family_id == claims.session_id}, ip=ip,
                only_changes=False)  # fmt: skip
    await session.commit()


