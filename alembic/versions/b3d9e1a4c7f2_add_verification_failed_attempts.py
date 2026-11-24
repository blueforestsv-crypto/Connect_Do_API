"""add failed_attempts to email verification tokens

Revision ID: b3d9e1a4c7f2
Revises: f07f5c91a4aa
Create Date: 2026-11-20

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3d9e1a4c7f2"
down_revision = "f07f5c91a4aa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_verification_tokens",
        sa.Column(
            "failed_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("email_verification_tokens", "failed_attempts")
