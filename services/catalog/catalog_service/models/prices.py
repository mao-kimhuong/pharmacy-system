"""Sell price history per pack unit (S8b): one row per change, written in the same
transaction as the change (a before-flush listener sees every path: edits, the
Excel import, hampers). Cost is not here: the catalog has none (reports merge
the receipts' cost)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Numeric, String, Uuid, event, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column

from pharmacy_shared import clock
from pharmacy_shared.db import IdMixin

from .base import Base
from .catalog import PackUnit


class PriceHistory(IdMixin, Base):
    __tablename__ = "pack_unit_price_history"
    __table_args__ = (Index("ix_price_history_pack_at", "pack_unit_id", "changed_at"),)

    medicine_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    pack_unit_id: Mapped[UUID] = mapped_column(Uuid)
    pack_unit: Mapped[str] = mapped_column(String(40))
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    new_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(10), default="change")  # change | backfill


@event.listens_for(Session, "before_flush")
def _record_prices(session: Session, flush_context: object, instances: object) -> None:
    actor = session.info.get("actor_id")
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, PackUnit):
            continue
        hist = inspect(obj).attrs.sell_price.history
        if obj in session.new:
            old, new = None, obj.sell_price
        elif hist.has_changes():
            old = hist.deleted[0] if hist.deleted else None
            new = obj.sell_price
        else:
            continue
        if new is None or (old is not None and Decimal(str(old)) == Decimal(str(new))):
            continue
        # new rows get their ids at flush: give them now, the history row needs them
        medicine = obj.__dict__.get("medicine")
        if medicine is not None and medicine.id is None:
            medicine.id = uuid4()
        obj.medicine_id = obj.medicine_id or (medicine.id if medicine is not None else None)
        obj.id = obj.id or uuid4()
        session.add(PriceHistory(medicine_id=obj.medicine_id, pack_unit_id=obj.id, pack_unit=obj.name,
                                 old_price=old, new_price=new, changed_at=clock.now(), changed_by=actor))  # fmt: skip
