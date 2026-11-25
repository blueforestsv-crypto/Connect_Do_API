"""Relación entre dos personas: contacto, permisos sobre el CV."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.application import Application
from app.models.contact_request import ContactRequest

CV_LINK_SECONDS = 600
_CV_TOKEN_TYPE = "cv"


async def get_contact_status(
    session: AsyncSession,
    me: uuid.UUID,
    other: uuid.UUID,
) -> tuple[str, uuid.UUID | None]:
    """none | pending_sent | pending_received | accepted (+ id de la solicitud)."""
    result = await session.execute(
        select(ContactRequest)
        .where(
            or_(
                and_(
                    ContactRequest.requester_id == me,
                    ContactRequest.receiver_id == other,
                ),
                and_(
                    ContactRequest.requester_id == other,
                    ContactRequest.receiver_id == me,
                ),
            ),
            ContactRequest.status.in_(("pending", "accepted")),
        )
        .order_by(ContactRequest.updated_at.desc())
    )
    request = result.scalars().first()

    if request is None:
        return "none", None
    if request.status == "accepted":
        return "accepted", request.id
    if request.requester_id == me:
        return "pending_sent", request.id
    return "pending_received", request.id


async def can_view_cv(
    session: AsyncSession,
    viewer_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> bool:
    """El dueño, sus contactos y quien recibió una postulación suya."""
    if viewer_id == owner_id:
        return True

    status, _ = await get_contact_status(session, viewer_id, owner_id)
    if status == "accepted":
        return True

    applied = await session.execute(
        select(Application.id)
        .where(
            Application.student_id == owner_id,
            Application.company_id == viewer_id,
        )
        .limit(1)
    )
    return applied.first() is not None


def create_cv_token(owner_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(owner_id),
            "type": _CV_TOKEN_TYPE,
            "iat": now,
            "exp": now + timedelta(seconds=CV_LINK_SECONDS),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_cv_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != _CV_TOKEN_TYPE:
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
