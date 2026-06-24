"""add messages

Revision ID: 686a9377beff
Revises: 66c014b3cd29
Create Date: 2026-06-24 02:19:05.236040

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '686a9377beff'
down_revision: Union[str, Sequence[str], None] = '66c014b3cd29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sender_id", sa.UUID(), nullable=False),
        sa.Column("receiver_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["receiver_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_messages_sender_id"),
        "messages",
        ["sender_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_messages_receiver_id"),
        "messages",
        ["receiver_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_messages_is_read"),
        "messages",
        ["is_read"],
        unique=False,
    )

    op.create_index(
        op.f("ix_messages_created_at"),
        "messages",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_created_at"), table_name="messages")
    op.drop_index(op.f("ix_messages_is_read"), table_name="messages")
    op.drop_index(op.f("ix_messages_receiver_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_sender_id"), table_name="messages")
    op.drop_table("messages")