"""add blocks, reports, user role and terms

Revision ID: b3e6f8a1d4c7
Revises: a1d5e7f9c3b2
Create Date: 2026-11-26

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b3e6f8a1d4c7"
down_revision = "a1d5e7f9c3b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), server_default="user", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "user_blocks",
        sa.Column("blocker_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("blocked_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blocker_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
    )
    op.create_index("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"])

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("resolution", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_type IN ('user', 'publication', 'comment', 'story', 'message')",
            name="ck_reports_target_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'dismissed', 'actioned')",
            name="ck_reports_status",
        ),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])
    op.create_index("ix_reports_target_user_id", "reports", ["target_user_id"])
    op.create_index("ix_reports_status", "reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_target_user_id", table_name="reports")
    op.drop_index("ix_reports_reporter_id", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_user_blocks_blocked_id", table_name="user_blocks")
    op.drop_table("user_blocks")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "role")
