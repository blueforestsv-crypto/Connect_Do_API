"""add applications table

Revision ID: f07f5c91a4aa
Revises: da6f8498442f
Create Date: 2026-06-29 13:44:26.065614

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f07f5c91a4aa"
down_revision: Union[str, Sequence[str], None] = "da6f8498442f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "profile_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("cv_url", sa.String(length=500), nullable=True),
        sa.Column("cover_message", sa.Text(), nullable=True),
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
            "status IN ('new', 'reviewed', 'contacted', 'interview', 'selected', 'rejected')",
            name="ck_applications_status",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["publications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publication_id",
            "student_id",
            name="uq_applications_publication_student",
        ),
    )

    op.create_index(
        op.f("ix_applications_publication_id"),
        "applications",
        ["publication_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_applications_student_id"),
        "applications",
        ["student_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_applications_company_id"),
        "applications",
        ["company_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_applications_status"),
        "applications",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_applications_status"), table_name="applications")
    op.drop_index(op.f("ix_applications_company_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_student_id"), table_name="applications")
    op.drop_index(op.f("ix_applications_publication_id"), table_name="applications")

    op.drop_table("applications")