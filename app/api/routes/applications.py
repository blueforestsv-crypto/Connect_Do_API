import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.application import Application
from app.models.message import Message
from app.models.notification import Notification
from app.models.publication import Publication
from app.models.user import User
from app.schemas.application import (
    ApplicationContactCreate,
    ApplicationContactResponse,
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
)

router = APIRouter(prefix="/applications", tags=["Applications"])

_RELATIONS = (
    selectinload(Application.publication),
    selectinload(Application.student).selectinload(User.profile),
    selectinload(Application.company),
)

# Texto que recibe el estudiante cuando la empresa cambia su estado.
_STATUS_NOTICES = {
    "reviewed": "revisó tu postulación",
    "interview": "quiere entrevistarte",
    "selected": "te seleccionó",
    "rejected": "decidió no continuar con tu postulación",
}


def _build_profile_snapshot(user: User) -> dict:
    profile = user.__dict__.get("profile")

    return {
        "user_id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": profile.phone if profile else None,
        "university": profile.university if profile else None,
        "academic_level": profile.academic_level if profile else None,
        "career": profile.career if profile else None,
        "academic_cycle": profile.academic_cycle if profile else None,
        "bio": profile.bio if profile else None,
        "portfolio_url": profile.portfolio_url if profile else None,
        "avatar_url": profile.avatar_url if profile else None,
        "profile_image_base64": profile.profile_image_base64 if profile else None,
        "cv_url": profile.cv_url if profile else None,
    }


def _get_full_name(user: User) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()

    if full_name:
        return full_name

    return user.email


async def _get_application_with_relations(
    session: AsyncSession,
    application_id: uuid.UUID,
) -> Application | None:
    result = await session.execute(
        select(Application)
        .options(
            *_RELATIONS,
        )
        .where(Application.id == application_id)
    )

    return result.scalar_one_or_none()


@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_application_endpoint(
    application_data: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApplicationResponse:
    publication_result = await session.execute(
        select(Publication).where(
            Publication.id == application_data.publication_id,
            Publication.is_active.is_(True),
        )
    )
    publication = publication_result.scalar_one_or_none()

    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La publicación no existe.",
        )

    if publication.author_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes postularte a tu propia publicación.",
        )

    student_result = await session.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(User.id == current_user.id)
    )
    profile_snapshot = _build_profile_snapshot(student_result.scalar_one())

    application = Application(
        publication_id=publication.id,
        student_id=current_user.id,
        company_id=publication.author_id,
        status="new",
        profile_snapshot=profile_snapshot,
        cv_url=profile_snapshot.get("cv_url"),
        cover_message=application_data.cover_message,
    )

    session.add(application)

    try:
        await session.flush()
        session.add(
            Notification(
                user_id=publication.author_id,
                type="application_new",
                title="Nueva postulación",
                message=f"{_get_full_name(current_user)} se postuló a "
                f"«{publication.title}».",
                related_user_id=current_user.id,
                related_publication_id=publication.id,
                is_read=False,
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya te postulaste a esta oportunidad.",
        )

    created_application = await _get_application_with_relations(
        session=session,
        application_id=application.id,
    )

    if created_application is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo cargar la postulación.",
        )

    return created_application


@router.get(
    "/me",
    response_model=list[ApplicationResponse],
)
async def list_my_applications_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApplicationResponse]:
    result = await session.execute(
        select(Application)
        .options(
            *_RELATIONS,
        )
        .where(Application.student_id == current_user.id)
        .order_by(Application.created_at.desc())
    )

    return list(result.scalars().all())


@router.get(
    "/received",
    response_model=list[ApplicationResponse],
)
async def list_received_applications_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApplicationResponse]:
    result = await session.execute(
        select(Application)
        .options(
            *_RELATIONS,
        )
        .where(Application.company_id == current_user.id)
        .order_by(Application.created_at.desc())
    )

    return list(result.scalars().all())


@router.get(
    "/publication/{publication_id}",
    response_model=list[ApplicationResponse],
)
async def list_publication_applications_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApplicationResponse]:
    publication_result = await session.execute(
        select(Publication).where(Publication.id == publication_id)
    )
    publication = publication_result.scalar_one_or_none()

    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La publicación no existe.",
        )

    if publication.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes ver las postulaciones de tus publicaciones.",
        )

    result = await session.execute(
        select(Application)
        .options(
            *_RELATIONS,
        )
        .where(Application.publication_id == publication_id)
        .order_by(Application.created_at.desc())
    )

    return list(result.scalars().all())


@router.patch(
    "/{application_id}",
    response_model=ApplicationResponse,
)
async def update_application_status_endpoint(
    application_id: uuid.UUID,
    application_data: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApplicationResponse:
    result = await session.execute(
        select(Application).where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()

    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La postulación no existe.",
        )

    if application.company_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes cambiar postulaciones que recibiste.",
        )

    changed = application.status != application_data.status
    application.status = application_data.status

    notice = _STATUS_NOTICES.get(application_data.status)
    if changed and notice:
        publication = await session.get(Publication, application.publication_id)
        title = publication.title if publication else "una oportunidad"
        session.add(
            Notification(
                user_id=application.student_id,
                type="application_status",
                title="Tu postulación",
                message=f"{_get_full_name(current_user)} {notice} en «{title}».",
                related_user_id=current_user.id,
                related_publication_id=application.publication_id,
                is_read=False,
            )
        )

    await session.commit()

    updated_application = await _get_application_with_relations(
        session=session,
        application_id=application.id,
    )

    if updated_application is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo cargar la postulación.",
        )

    return updated_application


@router.post(
    "/{application_id}/contact",
    response_model=ApplicationContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def contact_application_student_endpoint(
    application_id: uuid.UUID,
    contact_data: ApplicationContactCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApplicationContactResponse:
    result = await session.execute(
        select(Application)
        .options(
            *_RELATIONS,
        )
        .where(Application.id == application_id)
    )

    application = result.scalar_one_or_none()

    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La postulación no existe.",
        )

    if application.company_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes contactar a quien se postuló a tus publicaciones.",
        )

    clean_content = contact_data.content.strip()

    if not clean_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El mensaje no puede estar vacío.",
        )

    message = Message(
        sender_id=current_user.id,
        receiver_id=application.student_id,
        content=clean_content,
        is_read=False,
    )

    session.add(message)

    await session.flush()

    sender_name = _get_full_name(current_user)

    notification = Notification(
        user_id=application.student_id,
        type="message",
        title="Nuevo mensaje",
        message=f"{sender_name} te envió un mensaje sobre tu postulación.",
        related_user_id=current_user.id,
        related_message_id=message.id,
        is_read=False,
    )

    session.add(notification)

    application.status = "contacted"

    await session.commit()

    return ApplicationContactResponse(
        message_id=message.id,
        application_id=application.id,
        student_id=application.student_id,
        company_id=application.company_id,
        content=message.content,
    )


@router.delete(
    "/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirar mi postulación",
)
async def withdraw_application_endpoint(
    application_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    application = await session.get(Application, application_id)

    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La postulación no existe.")
    if application.student_id != current_user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo puedes retirar tus propias postulaciones.",
        )
    if application.status == "selected":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ya fuiste seleccionado; habla con la empresa para retirarte.",
        )

    await session.delete(application)
    await session.commit()
