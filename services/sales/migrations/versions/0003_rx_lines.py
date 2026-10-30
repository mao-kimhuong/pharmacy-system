"""prescription dispensing on invoice lines, dispensing label size

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-30 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LINE_COLUMNS = (
    ("rx_item_id", sa.Uuid()),
    ("prescription_id", sa.Uuid()),
    ("prescription_number", sa.String(length=32)),
    ("patient_id", sa.Uuid()),
    ("patient_name_en", sa.String(length=160)),
    ("patient_name_km", sa.String(length=160)),
    ("doctor_name", sa.String(length=160)),
    ("dosage", sa.String(length=160)),
    ("frequency", sa.String(length=160)),
    ("duration_days", sa.Integer()),
    ("warnings", sa.JSON()),
    ("allergy_override_reason", sa.String(length=255)),
    ("allergy_override_by", sa.Uuid()),
    ("warnings_acknowledged_by", sa.Uuid()),
    ("warnings_acknowledged_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.add_column(
        "branch_settings",
        sa.Column("dispensing_label_size", sa.String(length=10), server_default="70x40", nullable=False),
    )
    op.add_column("invoices", sa.Column("patient_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_invoices_patient_id"), "invoices", ["patient_id"], unique=False)
    for name, type_ in LINE_COLUMNS:
        op.add_column("invoice_lines", sa.Column(name, type_, nullable=True))
    op.create_index(op.f("ix_invoice_lines_rx_item_id"), "invoice_lines", ["rx_item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_invoice_lines_rx_item_id"), table_name="invoice_lines")
    for name, _ in reversed(LINE_COLUMNS):
        op.drop_column("invoice_lines", name)
    op.drop_index(op.f("ix_invoices_patient_id"), table_name="invoices")
    op.drop_column("invoices", "patient_id")
    op.drop_column("branch_settings", "dispensing_label_size")
