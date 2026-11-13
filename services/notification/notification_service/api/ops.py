"""T2 phase 4: till heartbeats, fridge sensors (device list + the devices' public readings endpoint)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.auth import CurrentUser, requires

from ..db import db
from ..schemas.telegram import (
    HeartbeatIn,
    ReadingIn,
    ReadingOut,
    SensorIn,
    SensorOut,
    SensorUpdate,
    WebhookOk,
)
from ..services import ops

router = APIRouter(tags=["operations"])
public = APIRouter(tags=["operations"])
manage = requires("notifications.manage")


@router.post("/heartbeat", response_model=WebhookOk)
async def heartbeat(body: HeartbeatIn, request: Request, user: CurrentUser = Depends(requires("pos.sell")),
                    session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """The POS says it is alive (every minute). During opening hours 10 minutes without any till → Telegram alert."""
    await ops.heartbeat(session, request.app.state.settings, user, body.branch_id, body.device_id)
    return {"ok": True}


def _out(d, token: str | None = None) -> dict:  # noqa: ANN001
    return {**{k: getattr(d, k) for k in ("id", "branch_id", "name", "min_c", "max_c", "is_active", "state",
                                          "last_reading_at", "last_temp_c")}, "token": token}  # fmt: skip


@router.get("/sensors", response_model=list[SensorOut])
async def sensors(user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)) -> list:
    return [_out(d) for d in await ops.list_devices(session, user)]


@router.post("/sensors", response_model=SensorOut, status_code=201)
async def add_sensor(body: SensorIn, user: CurrentUser = Depends(manage), session: AsyncSession = Depends(db.session)) -> dict:
    """A fridge thermometer of a branch (own branches; default range 2–8 °C). The token is shown only now."""
    d, token = await ops.create_device(session, user, body.model_dump())
    return _out(d, token)


@router.patch("/sensors/{device_id}", response_model=SensorOut)
async def edit_sensor(device_id: UUID, body: SensorUpdate, user: CurrentUser = Depends(manage),
                      session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    d, _ = await ops.update_device(session, user, device_id, body.model_dump(exclude_unset=True))
    return _out(d)


@router.post("/sensors/{device_id}/token", response_model=SensorOut)
async def new_sensor_token(device_id: UUID, user: CurrentUser = Depends(manage),
                           session: AsyncSession = Depends(db.session)) -> dict:  # fmt: skip
    """A new token for the device (the old one stops working at once)."""
    d, token = await ops.update_device(session, user, device_id, {}, new_token=True)
    return _out(d, token)


@public.post("/sensors/readings", response_model=ReadingOut)
async def sensor_reading(body: ReadingIn, request: Request, session: AsyncSession = Depends(db.session),
                         authorization: str | None = Header(default=None)) -> dict:  # fmt: skip
    """A device posts {"temperature_c": 5.4} with `Authorization: Bearer <its token>` (public, limited per IP).
    Unknown or deactivated token → 401; the fridge_sensors feature off → 404."""
    token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None
    d = await ops.reading(session, request.app.state.settings, token, body.temperature_c)
    return {"ok": True, "in_range": d.state == "ok", "state": d.state}
