"""add publication saves

Revision ID: c4f7a2e9d1b3
Revises: b8e4c1d2f3a6
Create Date: 2026-11-25

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c4f7a2e9d1b3"
down_revision = "b8e4c1d2f3a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publication_saves",
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["publications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("publication_id", "user_id"),
    )
    op.create_index("ix_publication_saves_user_id", "publication_saves", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_publication_saves_user_id", table_name="publication_saves")
    op.drop_table("publication_saves")
