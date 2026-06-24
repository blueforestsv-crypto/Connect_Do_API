"""add notifications

Revision ID: 70f1cbe8339c
Revises: 686a9377beff
Create Date: 2026-06-24 03:41:11.920029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70f1cbe8339c'
down_revision: Union[str, Sequence[str], None] = '686a9377beff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("related_user_id", sa.UUID(), nullable=True),
        sa.Column("related_publication_id", sa.UUID(), nullable=True),
        sa.Column("related_contact_request_id", sa.UUID(), nullable=True),
        sa.Column("related_message_id", sa.UUID(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["related_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["related_publication_id"],
            ["publications.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["related_contact_request_id"],
            ["contact_requests.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["related_message_id"],
            ["messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index(op.f("ix_notifications_type"), "notifications", ["type"], unique=False)
    op.create_index(op.f("ix_notifications_related_user_id"), "notifications", ["related_user_id"], unique=False)
    op.create_index(op.f("ix_notifications_related_publication_id"), "notifications", ["related_publication_id"], unique=False)
    op.create_index(op.f("ix_notifications_related_contact_request_id"), "notifications", ["related_contact_request_id"], unique=False)
    op.create_index(op.f("ix_notifications_related_message_id"), "notifications", ["related_message_id"], unique=False)
    op.create_index(op.f("ix_notifications_is_read"), "notifications", ["is_read"], unique=False)
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_is_read"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_related_message_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_related_contact_request_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_related_publication_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_related_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_type"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_table("notifications")
