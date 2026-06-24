"""add profile image base64

Revision ID: 618440ad0706
Revises: 98a614632c88
Create Date: 2026-06-23 23:52:30.697585

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '618440ad0706'
down_revision: Union[str, Sequence[str], None] = '98a614632c88'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("requester_id", sa.UUID(), nullable=False),
        sa.Column("receiver_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'cancelled')",
            name="ck_contact_requests_status",
        ),
        sa.CheckConstraint(
            "requester_id <> receiver_id",
            name="ck_contact_requests_not_same_user",
        ),
        sa.ForeignKeyConstraint(
            ["receiver_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "requester_id",
            "receiver_id",
            name="uq_contact_requests_requester_receiver",
        ),
    )

    op.create_index(
        op.f("ix_contact_requests_requester_id"),
        "contact_requests",
        ["requester_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_contact_requests_receiver_id"),
        "contact_requests",
        ["receiver_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_contact_requests_status"),
        "contact_requests",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_contact_requests_status"),
        table_name="contact_requests",
    )
    op.drop_index(
        op.f("ix_contact_requests_receiver_id"),
        table_name="contact_requests",
    )
    op.drop_index(
        op.f("ix_contact_requests_requester_id"),
        table_name="contact_requests",
    )
    op.drop_table("contact_requests")