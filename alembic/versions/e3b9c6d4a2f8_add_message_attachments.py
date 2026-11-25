"""add message attachments

Revision ID: e3b9c6d4a2f8
Revises: d2a8b5c3e7f1
Create Date: 2026-11-25

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e3b9c6d4a2f8"
down_revision = "d2a8b5c3e7f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages", sa.Column("attachment_type", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "messages", sa.Column("attachment_url", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "messages",
        sa.Column(
            "attachment_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "attachment_meta")
    op.drop_column("messages", "attachment_url")
    op.drop_column("messages", "attachment_type")
