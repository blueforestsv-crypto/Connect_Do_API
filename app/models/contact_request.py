import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class ContactRequest(Base):
    __tablename__ = "contact_requests"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'cancelled')",
            name="ck_contact_requests_status",
        ),
        CheckConstraint(
            "requester_id <> receiver_id",
            name="ck_contact_requests_not_same_user",
        ),
        UniqueConstraint(
            "requester_id",
            "receiver_id",
            name="uq_contact_requests_requester_receiver",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
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

    status: Mapped[str] = mapped_column(
        nullable=False,
        default="pending",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    requester: Mapped["User"] = relationship(
        "User",
        foreign_keys=[requester_id],
        back_populates="sent_contact_requests",
    )

    receiver: Mapped["User"] = relationship(
        "User",
        foreign_keys=[receiver_id],
        back_populates="received_contact_requests",
    )