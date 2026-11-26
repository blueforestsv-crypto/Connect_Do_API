"""Bloquear, reportar, moderar y eliminar la cuenta."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rate_limit import rate_limit
from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.contact_request import ContactRequest
from app.models.message import Message
from app.models.publication import Publication
from app.models.publication_interaction import PublicationComment
from app.models.safety import REPORT_REASONS, Report, UserBlock
from app.models.story import Story
from app.models.user import User
from app.services import media_service
from app.services.security import verify_password
from app.services.session_service import revoke_all_user_refresh_tokens

router = APIRouter(tags=["Safety"])


# =====================================================
# ESQUEMAS
# =====================================================
class BlockedUser(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    profile_image_base64: str | None = None
    blocked_at: datetime


class ReportCreate(BaseModel):
    target_type: Literal["user", "publication", "comment", "story", "message"]
    target_id: uuid.UUID
    reason: Literal[REPORT_REASONS]  # type: ignore[valid-type]
    details: str | None = Field(default=None, max_length=1000)


class ReportCreated(BaseModel):
    id: uuid.UUID
    message: str = "Gracias. Nuestro equipo revisará el reporte."


class AdminReport(BaseModel):
    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    target_user_id: uuid.UUID | None
    target_user_name: str | None = None
    reason: str
    details: str | None
    status: str
    resolution: str | None
    created_at: datetime
    reporter_name: str
    # Vista previa del contenido (texto o enlace de la imagen).
    preview: str | None = None
    reports_against_user: int = 0


class ResolveRequest(BaseModel):
    action: Literal["dismiss", "remove_content", "suspend_user"]


class DeleteAccountRequest(BaseModel):
    # Cuentas con contraseña: la contraseña. Cuentas solo con Google: el
    # texto "ELIMINAR".
    password: str | None = Field(default=None, max_length=128)
    confirm: str | None = Field(default=None, max_length=20)


def _name(user: User | None) -> str | None:
    if user is None:
        return None
    return f"{user.first_name} {user.last_name}".strip() or user.email


# =====================================================
# BLOQUEAR
# =====================================================
@router.post(
    "/users/{user_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bloquear a una persona",
)
async def block_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes bloquearte.")
    if await session.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")

    await session.execute(
        insert(UserBlock)
        .values(blocker_id=current_user.id, blocked_id=user_id)
        .on_conflict_do_nothing()
    )
    # Deja de ser contacto y se cancelan solicitudes pendientes.
    await session.execute(
        update(ContactRequest)
        .where(
            or_(
                and_(
                    ContactRequest.requester_id == current_user.id,
                    ContactRequest.receiver_id == user_id,
                ),
                and_(
                    ContactRequest.requester_id == user_id,
                    ContactRequest.receiver_id == current_user.id,
                ),
            ),
            ContactRequest.status.in_(("pending", "accepted")),
        )
        .values(status="cancelled")
    )
    await session.commit()


@router.delete(
    "/users/{user_id}/block",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desbloquear",
)
async def unblock_user(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.execute(
        delete(UserBlock).where(
            UserBlock.blocker_id == current_user.id,
            UserBlock.blocked_id == user_id,
        )
    )
    await session.commit()


@router.get(
    "/users/blocked", response_model=list[BlockedUser], summary="Mis bloqueados"
)
async def list_blocked(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[BlockedUser]:
    result = await session.execute(
        select(User, UserBlock.created_at)
        .join(UserBlock, UserBlock.blocked_id == User.id)
        .options(selectinload(User.profile))
        .where(UserBlock.blocker_id == current_user.id)
        .order_by(UserBlock.created_at.desc())
    )
    return [
        BlockedUser(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            profile_image_base64=(
                user.profile.profile_image_base64 if user.profile else None
            ),
            blocked_at=blocked_at,
        )
        for user, blocked_at in result.all()
    ]


# =====================================================
# REPORTAR
# =====================================================
async def _target_owner(
    session: AsyncSession, target_type: str, target_id: uuid.UUID
) -> uuid.UUID | None:
    """Dueño del contenido reportado; None si no existe."""
    if target_type == "user":
        user = await session.get(User, target_id)
        return user.id if user else None
    if target_type == "publication":
        item = await session.get(Publication, target_id)
        return item.author_id if item else None
    if target_type == "comment":
        item = await session.get(PublicationComment, target_id)
        return item.author_id if item else None
    if target_type == "story":
        item = await session.get(Story, target_id)
        return item.user_id if item else None
    if target_type == "message":
        item = await session.get(Message, target_id)
        return item.sender_id if item else None
    return None


@router.post(
    "/reports",
    response_model=ReportCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Reportar a una persona o un contenido",
    dependencies=[Depends(rate_limit("report", 20, 3600))],
)
async def create_report(
    data: ReportCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReportCreated:
    owner = await _target_owner(session, data.target_type, data.target_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ese contenido ya no existe.")
    if owner == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes reportarte.")

    # El mismo reporte pendiente no se duplica.
    existing = (
        await session.execute(
            select(Report).where(
                Report.reporter_id == current_user.id,
                Report.target_type == data.target_type,
                Report.target_id == data.target_id,
                Report.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return ReportCreated(id=existing.id)

    report = Report(
        reporter_id=current_user.id,
        target_type=data.target_type,
        target_id=data.target_id,
        target_user_id=owner,
        reason=data.reason,
        details=(data.details or "").strip() or None,
    )
    session.add(report)
    await session.commit()
    return ReportCreated(id=report.id)


# =====================================================
# MODERACIÓN (solo administradores)
# =====================================================
async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo para moderadores.")
    return current_user


async def _preview(session: AsyncSession, report: Report) -> str | None:
    if report.target_type == "publication":
        item = await session.get(Publication, report.target_id)
        if item is None:
            return None
        media = (item.media_items or [{}])[0] if item.media_items else {}
        text = f"{item.title}\n{item.description}"[:300]
        return f"{text}\n{media.get('url', '')}".strip()
    if report.target_type == "comment":
        item = await session.get(PublicationComment, report.target_id)
        return item.text[:300] if item else None
    if report.target_type == "story":
        item = await session.get(Story, report.target_id)
        return f"{item.caption or ''}\n{item.media_url}".strip() if item else None
    if report.target_type == "message":
        item = await session.get(Message, report.target_id)
        if item is None:
            return None
        return f"{item.content}\n{item.attachment_url or ''}".strip()[:300]
    return None


@router.get(
    "/admin/reports",
    response_model=list[AdminReport],
    summary="Reportes para revisar",
)
async def admin_list_reports(
    report_status: Literal["pending", "dismissed", "actioned"] = Query(
        default="pending", alias="status"
    ),
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[AdminReport]:
    result = await session.execute(
        select(Report)
        .where(Report.status == report_status)
        .order_by(Report.created_at.desc())
        .limit(100)
    )
    reports = list(result.scalars().all())

    items: list[AdminReport] = []
    for report in reports:
        reporter = await session.get(User, report.reporter_id)
        target_user = (
            await session.get(User, report.target_user_id)
            if report.target_user_id
            else None
        )
        against = 0
        if report.target_user_id:
            against = len(
                (
                    await session.execute(
                        select(Report.id).where(
                            Report.target_user_id == report.target_user_id
                        )
                    )
                ).all()
            )
        items.append(
            AdminReport(
                id=report.id,
                target_type=report.target_type,
                target_id=report.target_id,
                target_user_id=report.target_user_id,
                target_user_name=_name(target_user),
                reason=report.reason,
                details=report.details,
                status=report.status,
                resolution=report.resolution,
                created_at=report.created_at,
                reporter_name=_name(reporter) or "",
                preview=await _preview(session, report),
                reports_against_user=against,
            )
        )
    return items


@router.post(
    "/admin/reports/{report_id}/resolve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Resolver un reporte",
)
async def admin_resolve_report(
    report_id: uuid.UUID,
    data: ResolveRequest,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    report = await session.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El reporte no existe.")

    urls: list[str] = []
    if data.action == "remove_content":
        if report.target_type == "publication":
            item = await session.get(Publication, report.target_id)
            if item:
                item.is_active = False
        elif report.target_type == "comment":
            await session.execute(
                delete(PublicationComment).where(
                    PublicationComment.id == report.target_id
                )
            )
        elif report.target_type == "story":
            item = await session.get(Story, report.target_id)
            if item:
                urls.append(item.media_url)
                await session.delete(item)
        elif report.target_type == "message":
            item = await session.get(Message, report.target_id)
            if item:
                if item.attachment_url:
                    urls.append(item.attachment_url)
                item.content = "Mensaje eliminado por moderación."
                item.attachment_type = None
                item.attachment_url = None
                item.attachment_meta = None
        elif report.target_type == "user" and report.target_user_id:
            data = ResolveRequest(action="suspend_user")

    if data.action == "suspend_user" and report.target_user_id:
        user = await session.get(User, report.target_user_id)
        if user is not None and user.role != "admin":
            user.is_active = False
            await revoke_all_user_refresh_tokens(session=session, user_id=user.id)

    now = datetime.now(UTC)
    # El mismo contenido puede tener varios reportes: se resuelven juntos.
    await session.execute(
        update(Report)
        .where(
            Report.target_type == report.target_type,
            Report.target_id == report.target_id,
            Report.status == "pending",
        )
        .values(
            status="dismissed" if data.action == "dismiss" else "actioned",
            resolution=data.action,
            resolved_at=now,
        )
    )
    await session.commit()
    if urls:
        await media_service.destroy(urls)


# =====================================================
# ELIMINAR MI CUENTA
# =====================================================
@router.delete(
    "/auth/account",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar mi cuenta y todos mis datos",
)
async def delete_my_account(
    data: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    if current_user.hashed_password:
        if not data.password or not verify_password(
            data.password, current_user.hashed_password
        ):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "La contraseña no es correcta."
            )
    elif (data.confirm or "").strip().upper() != "ELIMINAR":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, 'Escribe "ELIMINAR" para confirmar.'
        )

    # Archivos en Cloudinary (mejor esfuerzo).
    urls: list[str] = []
    stories = await session.execute(
        select(Story.media_url).where(Story.user_id == current_user.id)
    )
    urls += [u for u in stories.scalars().all() if u]
    attachments = await session.execute(
        select(Message.attachment_url).where(
            Message.sender_id == current_user.id,
            Message.attachment_url.is_not(None),
        )
    )
    urls += [u for u in attachments.scalars().all() if u]
    publications = await session.execute(
        select(Publication.media_items).where(Publication.author_id == current_user.id)
    )
    for media_items in publications.scalars().all():
        for item in media_items or []:
            if isinstance(item, dict) and item.get("url"):
                urls.append(item["url"])

    # Todo lo demás se borra en cascada (perfil, publicaciones, mensajes,
    # contactos, postulaciones, CV, historias, notificaciones, sesiones).
    user_id = current_user.id
    session.expunge(current_user)
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
    await media_service.destroy(urls)
