import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    receiver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Adjunto opcional (Cloudinary): image | video | audio.
    attachment_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # width, height, duration (segundos), size_bytes.
    attachment_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Responder citando otro mensaje.
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Reacciones: {user_id: emoji}.
    reactions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # "Eliminado para todos".
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Se carga junto con el mensaje (solo un nivel).
    reply_to: Mapped["Message | None"] = relationship(
        "Message",
        remote_side="Message.id",
        lazy="selectin",
        join_depth=1,
    )

    sender: Mapped["User"] = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_messages",
    )

    receiver: Mapped["User"] = relationship(
        "User",
        foreign_keys=[receiver_id],
        back_populates="received_messages",
    )
