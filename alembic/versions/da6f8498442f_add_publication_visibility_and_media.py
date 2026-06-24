"""add publication visibility and media

Revision ID: da6f8498442f
Revises: 70f1cbe8339c
Create Date: 2026-06-24 12:39:26.696271

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql



# revision identifiers, used by Alembic.
revision: str = 'da6f8498442f'
down_revision: Union[str, Sequence[str], None] = '70f1cbe8339c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "publications",
        sa.Column(
            "visibility",
            sa.String(length=30),
            server_default="contacts",
            nullable=False,
        ),
    )

    op.add_column(
        "publications",
        sa.Column(
            "media_items",
            postgresql.JSONB(),
            nullable=True,
        ),
    )

    op.create_index(
        op.f("ix_publications_visibility"),
        "publications",
        ["visibility"],
        unique=False,
    )

    op.create_check_constraint(
        "ck_publications_visibility",
        "publications",
        "visibility IN ('public', 'contacts', 'private')",
    )

    op.alter_column(
        "publications",
        "visibility",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_publications_visibility",
        "publications",
        type_="check",
    )

    op.drop_index(
        op.f("ix_publications_visibility"),
        table_name="publications",
    )

    op.drop_column("publications", "media_items")
    op.drop_column("publications", "visibility")