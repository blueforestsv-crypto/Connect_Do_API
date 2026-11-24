"""add google oauth to users

Revision ID: c8f2a6d1e9b4
Revises: b3d9e1a4c7f2
Create Date: 2026-11-20

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c8f2a6d1e9b4"
down_revision = "b3d9e1a4c7f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("google_sub", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_users_google_sub"),
        "users",
        ["google_sub"],
        unique=True,
    )
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    # Las cuentas solo-Google no tienen contraseña: no se borran en silencio.
    google_only = (
        op.get_bind()
        .execute(sa.text("SELECT COUNT(*) FROM users WHERE hashed_password IS NULL"))
        .scalar_one()
    )
    if google_only:
        raise RuntimeError(
            f"Hay {google_only} cuentas sin contraseña (creadas con Google). "
            "Resuélvelas antes de revertir esta migración."
        )
    op.alter_column(
        "users",
        "hashed_password",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_column("users", "google_sub")
