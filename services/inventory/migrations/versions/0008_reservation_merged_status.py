"""reservation merged status

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31 12:34:51.299447
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_reservations_status", "reservations", type_="check")
    op.create_check_constraint("ck_reservations_status", "reservations",
                               "status IN ('reserved', 'confirmed', 'released', 'reversed', 'merged')")


def downgrade() -> None:
    op.drop_constraint("ck_reservations_status", "reservations", type_="check")
    op.create_check_constraint("ck_reservations_status", "reservations",
                               "status IN ('reserved', 'confirmed', 'released', 'reversed')")
