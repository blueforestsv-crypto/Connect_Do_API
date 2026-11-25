"""add stories

Revision ID: f4c1d8e2b6a9
Revises: e3b9c6d4a2f8
Create Date: 2026-11-25

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "f4c1d8e2b6a9"
down_revision = "e3b9c6d4a2f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.String(length=10), nullable=False),
        sa.Column("media_url", sa.String(length=500), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("caption", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stories_user_id", "stories", ["user_id"])
    op.create_index("ix_stories_expires_at", "stories", ["expires_at"])

    op.create_table(
        "story_views",
        sa.Column("story_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("viewer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["viewer_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("story_id", "viewer_id"),
    )
    op.create_index("ix_story_views_viewer_id", "story_views", ["viewer_id"])


def downgrade() -> None:
    op.drop_index("ix_story_views_viewer_id", table_name="story_views")
    op.drop_table("story_views")
    op.drop_index("ix_stories_expires_at", table_name="stories")
    op.drop_index("ix_stories_user_id", table_name="stories")
    op.drop_table("stories")
