"""/internal/v1 – called by other services, never through Traefik."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.errors import AppError, ErrorCode
from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..models import User
from ..schemas.auth import PinConsumeRequest
from ..services import pins
from ..services.access import load_permissions

router = APIRouter()


async def _redis(request: Request) -> Redis:
    return request.app.state.redis.client()


@router.post("/pin-tokens/consume")
async def consume_pin_token(
    body: PinConsumeRequest, caller: InternalCaller = Depends(internal_caller),
    session: AsyncSession = Depends(db.session), redis: Redis = Depends(_redis),
) -> dict:  # fmt: skip
    """Who typed the PIN (id, role, branches, permissions, pharmacist); the token is deleted."""
    return await pins.consume(session, redis, body.token, body.action, body.kind, caller.user_id)


@router.get("/users/{user_id}/access")
async def user_access(user_id: UUID, caller: InternalCaller = Depends(internal_caller),
                      session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """What a user may do right now (T2: a Telegram button tap is checked against this, not a copy):
    active, role, branches, permissions, pharmacist. Unknown → 404."""
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(ErrorCode.NOT_FOUND, "User not found", status_code=404)
    return {"user_id": str(user.id), "name": user.name, "role": user.role, "is_active": user.is_active,
            "is_pharmacist": user.is_pharmacist, "branch_ids": [str(b) for b in user.branch_ids],
            "permissions": await load_permissions(session, user.role) if user.is_active else []}  # fmt: skip
