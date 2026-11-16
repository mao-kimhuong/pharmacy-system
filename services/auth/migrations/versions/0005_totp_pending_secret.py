"""totp_pending_secret_enc: a new 2FA key waiting to be confirmed

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_pending_secret_enc", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "totp_pending_secret_enc")
