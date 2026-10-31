"""Outbox replay: GET /internal/v1/outbox?after_seq=&limit= on every service with
an outbox (added by create_service_app). Outbox rows are never deleted – the relay
only sets published_at – so a reader (the reports backfill) can rebuild its read
models from the exact past events, in seq order.

Internal only: /internal/v1 is not routed by Traefik, a valid service token is
required (401 otherwise) and only the services in OUTBOX_REPLAY_CALLERS may read
(default "reports"; 403 otherwise)."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from .errors import AppError, ErrorCode
from .internal import InternalCaller, internal_caller

MAX_PAGE = 1000


def replay_router(outbox_model: type) -> APIRouter:
    router = APIRouter()

    @router.get("/outbox")
    async def outbox(
        request: Request,
        after_seq: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE),
        caller: InternalCaller = Depends(internal_caller),
    ) -> dict[str, Any]:
        settings = request.app.state.settings
        if caller.service not in settings.outbox_replay_callers:
            raise AppError(ErrorCode.FORBIDDEN, "This service may not read the outbox", status_code=403)
        async with request.app.state.db.sessionmaker() as session:
            rows = (await session.execute(
                select(outbox_model).where(outbox_model.seq > after_seq).order_by(outbox_model.seq).limit(limit)
            )).scalars().all()  # fmt: skip
        items = [{"id": str(r.id), "seq": r.seq, "event_type": r.event_type, "payload": r.payload,
                  "created_at": r.created_at.isoformat()} for r in rows]  # fmt: skip
        return {"items": items, "next_after_seq": rows[-1].seq if rows else after_seq, "more": len(rows) == limit}

    return router
