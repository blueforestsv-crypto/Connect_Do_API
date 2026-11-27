"""add realtime chat features: reactions, replies, delete, presence, groups

Revision ID: e5c2f7a8b9d3
Revises: d8a3b6c9f2e4
Create Date: 2026-11-26

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e5c2f7a8b9d3"
down_revision = "d8a3b6c9f2e4"
branch_labels = None
depends_on = None


def _uuid(name: str, nullable: bool = False):
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _now(name: str):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Mensajes 1 a 1: responder citando, reacciones y eliminar para todos.
    op.add_column("messages", _uuid("reply_to_id", nullable=True))
    op.create_foreign_key(
        "fk_messages_reply_to",
        "messages",
        "messages",
        ["reply_to_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "messages",
        sa.Column("reactions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Grupos.
    op.create_table(
        "chat_groups",
        _uuid("id"),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        _uuid("created_by", nullable=True),
        _now("created_at"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chat_group_members",
        _uuid("group_id"),
        _uuid("user_id"),
        sa.Column("role", sa.String(length=10), nullable=False),
        _now("joined_at"),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["chat_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("ix_chat_group_members_user_id", "chat_group_members", ["user_id"])
    op.create_table(
        "group_messages",
        _uuid("id"),
        _uuid("group_id"),
        _uuid("sender_id", nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachment_type", sa.String(length=10), nullable=True),
        sa.Column("attachment_url", sa.String(length=500), nullable=True),
        sa.Column(
            "attachment_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        _uuid("reply_to_id", nullable=True),
        sa.Column("reactions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
        sa.ForeignKeyConstraint(["group_id"], ["chat_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reply_to_id"], ["group_messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_messages_group_id", "group_messages", ["group_id"])
    op.create_index("ix_group_messages_created_at", "group_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_group_messages_created_at", table_name="group_messages")
    op.drop_index("ix_group_messages_group_id", table_name="group_messages")
    op.drop_table("group_messages")
    op.drop_index("ix_chat_group_members_user_id", table_name="chat_group_members")
    op.drop_table("chat_group_members")
    op.drop_table("chat_groups")
    op.drop_column("messages", "deleted_at")
    op.drop_column("messages", "reactions")
    op.drop_constraint("fk_messages_reply_to", "messages", type_="foreignkey")
    op.drop_column("messages", "reply_to_id")
    op.drop_column("users", "last_seen_at")
