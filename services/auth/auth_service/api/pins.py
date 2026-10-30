from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, current_user

from ..db import db
from ..models import User
from ..schemas.auth import PinTokenOut, PinVerifyRequest, PinWitnessRequest, WitnessOut
from ..services import pins
from .auth import client_info, get_redis

router = APIRouter(tags=["pin"])


@router.post("/pin/verify", response_model=PinTokenOut)
async def verify_pin(
    body: PinVerifyRequest, request: Request, user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session), redis: Redis = Depends(get_redis),
) -> dict:  # fmt: skip
    """Your PIN for one action (e.g. controlled.dispense) → a one-time pin_token,
    valid 2 minutes. 5 wrong PINs lock the PIN for 15 minutes."""
    return await pins.verify(session, redis, user, body.pin, body.action, client_info(request).ip)


@router.post("/pin/witness", response_model=PinTokenOut)
async def witness_pin(
    body: PinWitnessRequest, request: Request, user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session), redis: Redis = Depends(get_redis),
) -> dict:  # fmt: skip
    """A second staff member types their own PIN on this device to witness your action."""
    return await pins.witness(session, redis, user, body.witness_user_id, body.pin, body.action,
                              client_info(request).ip)  # fmt: skip


@router.get("/pin/witnesses", response_model=list[WitnessOut])
async def list_witnesses(
    branch_id: UUID = Query(), user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(db.session),
) -> list[User]:  # fmt: skip
    """Staff at the branch who have a PIN (to pick a witness)."""
    return await pins.witnesses(session, user, branch_id)
