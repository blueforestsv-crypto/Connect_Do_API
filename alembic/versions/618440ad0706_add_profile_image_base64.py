"""add profile image base64

Revision ID: 618440ad0706
Revises: 98a614632c88
Create Date: 2026-06-23

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "618440ad0706"
down_revision = "98a614632c88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("profile_image_base64", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("profiles", "profile_image_base64")