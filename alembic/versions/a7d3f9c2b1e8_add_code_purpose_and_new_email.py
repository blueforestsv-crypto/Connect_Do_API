"""add purpose and new_email to email verification tokens

Revision ID: a7d3f9c2b1e8
Revises: e5a1c3b7d9f0
Create Date: 2026-11-25

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7d3f9c2b1e8"
down_revision = "e5a1c3b7d9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_verification_tokens",
        sa.Column(
            "purpose",
            sa.String(length=30),
            server_default="verify_email",
            nullable=False,
        ),
    )
    op.add_column(
        "email_verification_tokens",
        sa.Column("new_email", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_email_verification_tokens_purpose"),
        "email_verification_tokens",
        ["purpose"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_email_verification_tokens_purpose"),
        table_name="email_verification_tokens",
    )
    op.drop_column("email_verification_tokens", "new_email")
    op.drop_column("email_verification_tokens", "purpose")
