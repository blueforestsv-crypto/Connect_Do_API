"""add user stickers

Revision ID: a1d5e7f9c3b2
Revises: f4c1d8e2b6a9
Create Date: 2026-11-26

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a1d5e7f9c3b2"
down_revision = "f4c1d8e2b6a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_stickers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "url", name="uq_user_sticker"),
    )
    op.create_index("ix_user_stickers_user_id", "user_stickers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_stickers_user_id", table_name="user_stickers")
    op.drop_table("user_stickers")
