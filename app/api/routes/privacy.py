"""Privacidad, sesiones activas, descarga de mis datos y errores de la app."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_optional_user
from app.api.routes.safety import require_admin
from app.core.rate_limit import rate_limit
from app.db.session import get_db_session
from app.models.chat_group import ChatGroupMember, GroupMessage
from app.models.client_error import ClientError
from app.models.contact_request import ContactRequest
from app.models.message import Message
from app.models.publication import Publication
from app.models.publication_interaction import PublicationComment
from app.models.refresh_token import RefreshToken
from app.models.social import Follow
from app.models.user import User

router = APIRouter(tags=["Privacy"])


# =====================================================
# AJUSTES DE PRIVACIDAD
# =====================================================
class PrivacySettings(BaseModel):
    # Quién puede escribirme por primera vez.
    message_privacy: Literal["contacts", "everyone"] = "contacts"
    # Quién ve mis historias: contactos, o también quienes me siguen.
    story_privacy: Literal["contacts", "followers"] = "contacts"
    # Mostrar "en línea" y "últ. vez".
    show_presence: bool = True


class PrivacyUpdate(BaseModel):
    message_privacy: Literal["contacts", "everyone"] | None = None
    story_privacy: Literal["contacts", "followers"] | None = None
    show_presence: bool | None = None


def _privacy(user: User) -> PrivacySettings:
    return PrivacySettings(
        message_privacy=user.message_privacy,
        story_privacy=user.story_privacy,
        show_presence=user.show_presence,
    )


@router.get("/auth/privacy", response_model=PrivacySettings)
async def get_privacy(
    current_user: User = Depends(get_current_user),
) -> PrivacySettings:
    return _privacy(current_user)


@router.patch("/auth/privacy", response_model=PrivacySettings)
async def update_privacy(
    data: PrivacyUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PrivacySettings:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(current_user, field, value)
    await session.commit()
    return _privacy(current_user)


# =====================================================
# SESIONES ACTIVAS
# =====================================================
class SessionOut(BaseModel):
    id: uuid.UUID
    # Para que la app reconozca cuál es la suya.
    jti: str
    device_name: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None


@router.get("/auth/sessions", response_model=list[SessionOut])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[SessionOut]:
    rows = await session.execute(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(UTC),
        )
        .order_by(RefreshToken.created_at.desc())
    )
    return [
        SessionOut(
            id=t.id,
            jti=t.jti,
            device_name=t.device_name,
            created_at=t.created_at,
            last_used_at=t.last_used_at,
        )
        for t in rows.scalars().all()
    ]


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == session_id,
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()


class KeepSession(BaseModel):
    keep_jti: str = Field(min_length=1, max_length=64)


@router.post("/auth/sessions/revoke-others")
async def revoke_other_sessions(
    data: KeepSession,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    result = await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.jti != data.keep_jti,
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return {"revoked": result.rowcount or 0}


# =====================================================
# DESCARGAR MIS DATOS
# =====================================================
def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get(
    "/auth/account/export",
    summary="Descargar una copia de mis datos (JSON)",
    dependencies=[Depends(rate_limit("data_export", 3, 3600))],
)
async def export_my_data(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    uid = current_user.id
    await session.refresh(current_user, ["profile"])
    profile = current_user.profile

    publications = (
        (
            await session.execute(
                select(Publication)
                .where(Publication.author_id == uid)
                .order_by(Publication.created_at)
            )
        )
        .scalars()
        .all()
    )
    comments = (
        (
            await session.execute(
                select(PublicationComment)
                .where(PublicationComment.author_id == uid)
                .order_by(PublicationComment.created_at)
            )
        )
        .scalars()
        .all()
    )
    messages = (
        (
            await session.execute(
                select(Message)
                .where(or_(Message.sender_id == uid, Message.receiver_id == uid))
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    group_ids = select(ChatGroupMember.group_id).where(ChatGroupMember.user_id == uid)
    group_messages = (
        (
            await session.execute(
                select(GroupMessage)
                .where(
                    GroupMessage.sender_id == uid, GroupMessage.group_id.in_(group_ids)
                )
                .order_by(GroupMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    contacts = (
        (
            await session.execute(
                select(ContactRequest).where(
                    or_(
                        ContactRequest.requester_id == uid,
                        ContactRequest.receiver_id == uid,
                    ),
                    ContactRequest.status == "accepted",
                )
            )
        )
        .scalars()
        .all()
    )
    following = (
        (
            await session.execute(
                select(Follow.followed_id).where(Follow.follower_id == uid)
            )
        )
        .scalars()
        .all()
    )
    followers = (
        (
            await session.execute(
                select(Follow.follower_id).where(Follow.followed_id == uid)
            )
        )
        .scalars()
        .all()
    )

    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {
            "id": str(uid),
            "email": current_user.email,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "account_type": current_user.account_type,
            "created_at": _iso(current_user.created_at),
            "privacy": _privacy(current_user).model_dump(),
        },
        "profile": (
            {
                key: value
                for key, value in {
                    "career": getattr(profile, "career", None),
                    "university": getattr(profile, "university", None),
                    "bio": getattr(profile, "bio", None),
                    "headline": getattr(profile, "headline", None),
                    "skills": getattr(profile, "skills", None),
                    "location": getattr(profile, "location", None),
                    "company_name": getattr(profile, "company_name", None),
                }.items()
                if value
            }
            if profile
            else None
        ),
        "publications": [
            {
                "id": str(p.id),
                "type": p.type,
                "title": p.title,
                "description": p.description,
                "visibility": getattr(p, "visibility", None),
                "created_at": _iso(p.created_at),
            }
            for p in publications
        ],
        "comments": [
            {
                "publication_id": str(c.publication_id),
                "text": c.text,
                "created_at": _iso(c.created_at),
            }
            for c in comments
        ],
        "messages": [
            {
                "with": str(m.receiver_id if m.sender_id == uid else m.sender_id),
                "sent_by_me": m.sender_id == uid,
                "content": "" if m.deleted_at else m.content,
                "attachment_url": None if m.deleted_at else m.attachment_url,
                "created_at": _iso(m.created_at),
            }
            for m in messages
        ],
        "group_messages": [
            {
                "group_id": str(m.group_id),
                "content": "" if m.deleted_at else m.content,
                "attachment_url": None if m.deleted_at else m.attachment_url,
                "created_at": _iso(m.created_at),
            }
            for m in group_messages
        ],
        "contacts": [
            str(c.receiver_id if c.requester_id == uid else c.requester_id)
            for c in contacts
        ],
        "following": [str(x) for x in following],
        "followers": [str(x) for x in followers],
    }
    return JSONResponse(
        data,
        headers={
            "Content-Disposition": 'attachment; filename="connect_do_mis_datos.json"'
        },
    )


# =====================================================
# ERRORES DE LA APP
# =====================================================
class ClientErrorIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    stack: str | None = Field(default=None, max_length=20000)
    platform: str | None = Field(default=None, max_length=40)
    app_version: str | None = Field(default=None, max_length=40)
    screen: str | None = Field(default=None, max_length=120)


@router.post(
    "/client-errors",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("client_error", 20, 600))],
)
async def report_client_error(
    data: ClientErrorIn,
    user: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    session.add(
        ClientError(
            user_id=user.id if user else None,
            message=data.message[:500],
            stack=(data.stack or "")[:20000] or None,
            platform=data.platform,
            app_version=data.app_version,
            screen=data.screen,
        )
    )
    await session.commit()


class ClientErrorOut(BaseModel):
    id: uuid.UUID
    message: str
    stack: str | None = None
    platform: str | None = None
    app_version: str | None = None
    screen: str | None = None
    user_id: uuid.UUID | None = None
    created_at: datetime


@router.get("/admin/client-errors", response_model=list[ClientErrorOut])
async def list_client_errors(
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[ClientErrorOut]:
    # Se guardan 30 días.
    await session.execute(
        delete(ClientError).where(
            ClientError.created_at < datetime.now(UTC) - timedelta(days=30)
        )
    )
    await session.commit()
    rows = await session.execute(
        select(ClientError).order_by(ClientError.created_at.desc()).limit(limit)
    )
    return [
        ClientErrorOut.model_validate(e, from_attributes=True) for e in rows.scalars()
    ]
