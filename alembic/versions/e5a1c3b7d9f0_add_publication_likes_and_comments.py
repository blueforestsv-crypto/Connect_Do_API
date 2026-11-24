"""add publication likes and comments

Revision ID: e5a1c3b7d9f0
Revises: c8f2a6d1e9b4
Create Date: 2026-11-20

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e5a1c3b7d9f0"
down_revision = "c8f2a6d1e9b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publication_likes",
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["publications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("publication_id", "user_id"),
    )
    op.create_index(
        op.f("ix_publication_likes_user_id"),
        "publication_likes",
        ["user_id"],
    )

    op.create_table(
        "publication_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["publication_id"], ["publications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_publication_comments_author_id"),
        "publication_comments",
        ["author_id"],
    )
    op.create_index(
        "ix_publication_comments_publication_created",
        "publication_comments",
        ["publication_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publication_comments_publication_created",
        table_name="publication_comments",
    )
    op.drop_index(
        op.f("ix_publication_comments_author_id"),
        table_name="publication_comments",
    )
    op.drop_table("publication_comments")
    op.drop_index(op.f("ix_publication_likes_user_id"), table_name="publication_likes")
    op.drop_table("publication_likes")
