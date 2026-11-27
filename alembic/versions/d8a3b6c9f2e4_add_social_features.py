"""add social features

Revision ID: d8a3b6c9f2e4
Revises: c7f2a9d5e1b8
Create Date: 2026-11-26

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "d8a3b6c9f2e4"
down_revision = "c7f2a9d5e1b8"
branch_labels = None
depends_on = None


def _uuid(name: str):
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=False)


def _created():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "follows",
        _uuid("follower_id"),
        _uuid("followed_id"),
        _created(),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["followed_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("follower_id", "followed_id"),
    )
    op.create_index("ix_follows_followed_id", "follows", ["followed_id"])

    # Respuestas y me gusta en comentarios; menciones.
    op.add_column(
        "publication_comments",
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_publication_comments_parent",
        "publication_comments",
        "publication_comments",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_publication_comments_parent_id", "publication_comments", ["parent_id"]
    )
    op.add_column(
        "publication_comments",
        sa.Column("mentions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "publications",
        sa.Column("mentions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "comment_likes",
        _uuid("comment_id"),
        _uuid("user_id"),
        _created(),
        sa.ForeignKeyConstraint(
            ["comment_id"], ["publication_comments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("comment_id", "user_id"),
    )

    op.create_table(
        "story_highlights",
        _uuid("id"),
        _uuid("user_id"),
        sa.Column("title", sa.String(length=40), nullable=False),
        _created(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_story_highlights_user_id", "story_highlights", ["user_id"])

    op.create_table(
        "story_highlight_items",
        _uuid("id"),
        _uuid("highlight_id"),
        sa.Column("media_type", sa.String(length=10), nullable=False),
        sa.Column("media_url", sa.String(length=500), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("caption", sa.String(length=200), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(
            ["highlight_id"], ["story_highlights.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_story_highlight_items_highlight_id",
        "story_highlight_items",
        ["highlight_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_story_highlight_items_highlight_id", table_name="story_highlight_items"
    )
    op.drop_table("story_highlight_items")
    op.drop_index("ix_story_highlights_user_id", table_name="story_highlights")
    op.drop_table("story_highlights")
    op.drop_table("comment_likes")
    op.drop_column("publications", "mentions")
    op.drop_column("publication_comments", "mentions")
    op.drop_index(
        "ix_publication_comments_parent_id", table_name="publication_comments"
    )
    op.drop_constraint(
        "fk_publication_comments_parent", "publication_comments", type_="foreignkey"
    )
    op.drop_column("publication_comments", "parent_id")
    op.drop_index("ix_follows_followed_id", table_name="follows")
    op.drop_table("follows")
