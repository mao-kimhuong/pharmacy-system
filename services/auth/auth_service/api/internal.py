"""/internal/v1 – called by other services, never through Traefik."""

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.internal import InternalCaller, internal_caller

from ..db import db
from ..schemas.auth import PinConsumeRequest
from ..services import pins

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
