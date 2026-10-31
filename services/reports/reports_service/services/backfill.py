"""Backfill: rebuild the read models from each service's history by replaying
its outbox (GET /internal/v1/outbox?after_seq=, service token; rows are never
deleted). Events go through the same handlers as live ones, with the same
message id (the outbox id), so the live consumer and the backfill never apply
an event twice, and running the backfill again changes nothing.

--rebuild empties the read models (and the seen-message list and cursors)
first; then everything is applied again from the start."""

import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pharmacy_shared.db import Database
from pharmacy_shared.internal import InternalClient

from ..config import Settings
from ..models import Base, ProcessedMessage, ReplayCursor
from . import events

log = logging.getLogger(__name__)
KEEP = {"outbox", "alembic_version"}


def _pattern(key: str) -> re.Pattern[str]:
    """RabbitMQ topic key → regex ("*" = exactly one word)."""
    return re.compile("^" + r"\.".join("[^.]+" if w == "*" else re.escape(w) for w in key.split(".")) + "$")


PATTERNS = [_pattern(k) for k in events.ROUTING_KEYS]


def wanted(event_type: str) -> bool:
    return any(p.match(event_type) for p in PATTERNS)


async def truncate(session: AsyncSession) -> None:
    tables = [t.name for t in Base.metadata.sorted_tables if t.name not in KEEP]
    await session.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE"))  # noqa: S608 – own table names
    await session.commit()


async def apply(session: AsyncSession, item: dict[str, Any]) -> bool:
    """One replayed event, in the caller's transaction. False when already applied."""
    if not wanted(item["event_type"]):
        return False
    message_id = UUID(item["id"])
    new = await session.execute(insert(ProcessedMessage).values(message_id=message_id, event_type=item["event_type"])
                                .on_conflict_do_nothing().returning(ProcessedMessage.message_id))  # fmt: skip
    if new.scalar_one_or_none() is None:
        return False
    token = events.event_time.set(events.datetime.fromisoformat(item["created_at"]))
    try:
        await events.handle_event(session, item["event_type"], item["payload"], message_id)
    finally:
        events.event_time.reset(token)
    return True


async def replay_service(db: Database, client: InternalClient, service: str, page_size: int) -> dict[str, int]:
    applied = read = 0
    while True:
        async with db.sessionmaker() as session:
            cursor = await session.get(ReplayCursor, service) or ReplayCursor(service=service, after_seq=0, events=0)
            page = await client.get("/outbox", {"after_seq": cursor.after_seq, "limit": page_size})
            for item in page["items"]:
                async with session.begin_nested():
                    applied += await apply(session, item)
            read += len(page["items"])
            cursor.after_seq, cursor.events = page["next_after_seq"], cursor.events + len(page["items"])
            session.add(cursor)
            await session.commit()
        if not page["more"]:
            return {"read": read, "applied": applied}


async def backfill(db: Database, settings: Settings, services: list[str] | None = None, rebuild: bool = False,
                   clients: dict[str, InternalClient] | None = None) -> dict[str, dict[str, int]]:  # fmt: skip
    if rebuild:
        async with db.sessionmaker() as session:
            await truncate(session)
    done = {}
    for service in services or list(settings.replay_sources):
        client = (clients or {}).get(service) or InternalClient(
            settings.replay_url_template.format(service=service), settings.service_name, settings.service_token,
            read_timeout=60)  # fmt: skip
        done[service] = await replay_service(db, client, service, settings.replay_page_size)
        log.info("backfill %s: %s", service, done[service])
    return done


async def cursors(db: Database) -> list[dict[str, Any]]:
    async with db.sessionmaker() as session:
        rows = (await session.execute(select(ReplayCursor).order_by(ReplayCursor.service))).scalars()
        return [{"service": r.service, "after_seq": r.after_seq, "events": r.events} for r in rows]
