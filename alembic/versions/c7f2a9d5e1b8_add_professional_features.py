"""add professional features

Revision ID: c7f2a9d5e1b8
Revises: b3e6f8a1d4c7
Create Date: 2026-11-26

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c7f2a9d5e1b8"
down_revision = "b3e6f8a1d4c7"
branch_labels = None
depends_on = None


def _id(name: str = "id"):
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=False)


def _created():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "account_type",
            sa.String(length=20),
            server_default="student",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "company_verified", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "company_verification_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    for column, length in (
        ("company_name", 160),
        ("company_sector", 120),
        ("company_size", 30),
        ("headline", 160),
    ):
        op.add_column(
            "profiles", sa.Column(column, sa.String(length=length), nullable=True)
        )

    op.create_table(
        "profile_entries",
        _id(),
        _id("user_id"),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("organization", sa.String(length=160), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        _created(),
        sa.CheckConstraint(
            "kind IN ('experience', 'education', 'certification', 'project', "
            "'language', 'volunteer')",
            name="ck_profile_entries_kind",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_profile_entries_user_id", "profile_entries", ["user_id"])

    op.create_table(
        "skill_endorsements",
        _id(),
        _id("user_id"),
        sa.Column("skill", sa.String(length=50), nullable=False),
        _id("endorser_id"),
        _created(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["endorser_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "skill", "endorser_id", name="uq_skill_endorsement"
        ),
    )
    op.create_index("ix_skill_endorsements_user_id", "skill_endorsements", ["user_id"])

    op.create_table(
        "profile_views",
        _id(),
        _id("viewer_id"),
        _id("viewed_id"),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["viewer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["viewed_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("viewer_id", "viewed_id", "day", name="uq_profile_view"),
    )
    op.create_index("ix_profile_views_viewed_id", "profile_views", ["viewed_id"])

    op.create_table(
        "job_alerts",
        _id(),
        _id("user_id"),
        sa.Column("query", sa.String(length=100), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=True),
        sa.Column("modality", sa.String(length=20), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_alerts_user_id", "job_alerts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_job_alerts_user_id", table_name="job_alerts")
    op.drop_table("job_alerts")
    op.drop_index("ix_profile_views_viewed_id", table_name="profile_views")
    op.drop_table("profile_views")
    op.drop_index("ix_skill_endorsements_user_id", table_name="skill_endorsements")
    op.drop_table("skill_endorsements")
    op.drop_index("ix_profile_entries_user_id", table_name="profile_entries")
    op.drop_table("profile_entries")
    for column in ("headline", "company_size", "company_sector", "company_name"):
        op.drop_column("profiles", column)
    op.drop_column("users", "company_verification_requested_at")
    op.drop_column("users", "company_verified")
    op.drop_column("users", "account_type")
