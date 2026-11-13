"""The staff side of the bot (bot.HOOKS): approval buttons (phase 2) and commands (phase 3)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from . import approvals
from .telegram import Sender


class Hooks:
    def __init__(self, clients: approvals.Clients | None = None) -> None:
        self._clients = clients

    def clients(self, settings: Settings) -> approvals.Clients:
        return self._clients or approvals.default_clients(settings)

    async def callback(self, session: AsyncSession, settings: Settings, sender: Sender, cb: dict[str, Any],
                       reply: Any) -> None:  # fmt: skip
        if str(cb.get("data") or "").startswith("ap:"):
            await approvals.tap(session, settings, sender, cb, self.clients(settings))

    async def command(self, session: AsyncSession, settings: Settings, command: str, arg: str, chat_id: str,
                      user_id: str, private: bool, reply: Any) -> bool:  # fmt: skip
        """True when the command was a staff command (answered here)."""
        return False
