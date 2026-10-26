"""SQLAlchemy models of the branch service. Import every model here so
Alembic autogenerate can see it."""

from pharmacy_shared.db import Base
from pharmacy_shared.outbox import OutboxMixin

from .branch import DEFAULT_EXPIRY_ALERT_DAYS, Branch, BranchSettings, FeatureSwitch


class OutboxEvent(OutboxMixin, Base):
    __tablename__ = "outbox"


__all__ = ["Base", "Branch", "BranchSettings", "DEFAULT_EXPIRY_ALERT_DAYS", "FeatureSwitch", "OutboxEvent"]
