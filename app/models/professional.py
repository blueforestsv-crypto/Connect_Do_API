"""Lo profesional del perfil: experiencia y formación, validaciones de
habilidades, visitas al perfil y alertas de empleo."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

ENTRY_KINDS = (
    "experience",
    "education",
    "certification",
    "project",
    "language",
    "volunteer",
)


class ProfileEntry(Base):
    """Una línea del perfil: un trabajo, un estudio, una certificación…"""

    __tablename__ = "profile_entries"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('experience', 'education', 'certification', 'project', "
            "'language', 'volunteer')",
            name="ck_profile_entries_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Cargo, carrera, nombre del certificado o proyecto, idioma…
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    # Empresa, universidad, institución que certifica, nivel del idioma…
    organization: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SkillEndorsement(Base):
    """Un contacto confirma que [user] sabe [skill]."""

    __tablename__ = "skill_endorsements"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "skill", "endorser_id", name="uq_skill_endorsement"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill: Mapped[str] = mapped_column(String(50), nullable=False)
    endorser_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProfileView(Base):
    """[viewer] vio el perfil de [viewed]. Una fila por persona y día."""

    __tablename__ = "profile_views"
    __table_args__ = (
        UniqueConstraint("viewer_id", "viewed_id", "day", name="uq_profile_view"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    viewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    viewed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobAlert(Base):
    """Avísame de oportunidades nuevas que coincidan con esto."""

    __tablename__ = "job_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query: Mapped[str | None] = mapped_column(String(100), nullable=True)
    type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    modality: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
