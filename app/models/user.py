import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


if TYPE_CHECKING:
    from app.models.profile import Profile
    from app.models.email_verification_token import EmailVerificationToken
    from app.models.publication import Publication
    from app.models.contact_request import ContactRequest
    from app.models.message import Message
    from app.models.notification import Notification


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    first_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    last_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
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

    profile: Mapped["Profile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    email_verification_tokens: Mapped[list["EmailVerificationToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    publications: Mapped[list["Publication"]] = relationship(
        "Publication",
        back_populates="author",
        cascade="all, delete-orphan",
    )

    sent_contact_requests: Mapped[list["ContactRequest"]] = relationship(
        "ContactRequest",
        foreign_keys="ContactRequest.requester_id",
        back_populates="requester",
        cascade="all, delete-orphan",
    )

    received_contact_requests: Mapped[list["ContactRequest"]] = relationship(
        "ContactRequest",
        foreign_keys="ContactRequest.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan",
    )

    sent_messages: Mapped[list["Message"]] = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender",
        cascade="all, delete-orphan",
    )

    received_messages: Mapped[list["Message"]] = relationship(
        "Message",
        foreign_keys="Message.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan",
    )

    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        foreign_keys="Notification.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def profile_image_base64(self) -> str | None:
        profile = self.__dict__.get("profile")

        if profile is None:
            return None

        return profile.profile_image_base64