"""T2 phase 4: heartbeats, opening, fridge sensors

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "heartbeats",
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("branch_id", "device_id"),
    )
    op.create_table(
        "branch_ops",
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("offline_since", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("branch_id"),
    )
    op.create_table(
        "branch_days",
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("first_sale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("late_alerted", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("branch_id", "day"),
    )
    op.create_table(
        "features",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "sensor_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("branch_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("min_c", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("max_c", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=8), nullable=False),
        sa.Column("out_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("out_alerted", sa.Boolean(), nullable=False),
        sa.Column("silent_alerted", sa.Boolean(), nullable=False),
        sa.Column("last_reading_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_temp_c", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sensor_devices_branch_id", "sensor_devices", ["branch_id"])
    op.create_index("uq_sensor_devices_token", "sensor_devices", ["token_hash"], unique=True)
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temp_c", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("in_range", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sensor_readings_device_at", "sensor_readings", ["device_id", "at"])


def downgrade() -> None:
    for table in ("sensor_readings", "sensor_devices", "features", "branch_days", "branch_ops", "heartbeats"):
        op.drop_table(table)
