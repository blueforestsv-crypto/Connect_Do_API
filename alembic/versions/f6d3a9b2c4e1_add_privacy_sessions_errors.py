"""add privacy settings, session devices and client errors

Revision ID: f6d3a9b2c4e1
Revises: e5c2f7a8b9d3
Create Date: 2026-11-27

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f6d3a9b2c4e1"
down_revision = "e5c2f7a8b9d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Privacidad: quién me escribe, quién ve mis historias, si muestro
    # "en línea / últ. vez".
    op.add_column(
        "users",
        sa.Column(
            "message_privacy",
            sa.String(length=10),
            server_default="contacts",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "story_privacy",
            sa.String(length=10),
            server_default="contacts",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "show_presence", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )

    # Sesiones activas: en qué dispositivo y cuándo se usó por última vez.
    op.add_column(
        "refresh_tokens", sa.Column("device_name", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "client_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("stack", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=40), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("screen", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_client_errors_created_at", "client_errors", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_client_errors_created_at", table_name="client_errors")
    op.drop_table("client_errors")
    op.drop_column("refresh_tokens", "last_used_at")
    op.drop_column("refresh_tokens", "device_name")
    op.drop_column("users", "show_presence")
    op.drop_column("users", "story_privacy")
    op.drop_column("users", "message_privacy")
