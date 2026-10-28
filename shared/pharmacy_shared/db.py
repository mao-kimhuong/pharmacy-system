import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def make_base() -> type[DeclarativeBase]:
    """A new declarative base with its own MetaData. Each service has one
    (`<service>_service/models/base.py`), so the models of several services can
    be loaded in one process (the sales tests run inventory and customers too)."""

    class Base(DeclarativeBase):
        pass

    return Base


class IdMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Database:
    """Lazily created engine, so importing an app never opens a connection.

    The engine is tied to the event loop that first used it. In production there
    is one loop; in tests each test may run its own loop, so a new engine is made
    when the loop changes instead of reusing connections from a closed loop.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure(self) -> None:
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._engine is None or (loop is not None and loop is not self._loop):
            self._engine = create_async_engine(self.url, pool_pre_ping=True)
            self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
            self._loop = loop

    @property
    def engine(self) -> AsyncEngine:
        self._ensure()
        assert self._engine is not None
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        self._ensure()
        assert self._sessionmaker is not None
        return self._sessionmaker

    async def session(self) -> AsyncIterator[AsyncSession]:
        """FastAPI dependency: one session per request."""
        async with self.sessionmaker() as session:
            yield session

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None
        self._loop = None
