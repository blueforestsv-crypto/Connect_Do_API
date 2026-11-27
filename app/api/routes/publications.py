import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.professional import JOB_TYPES, notify_job_alerts
from app.core.rate_limit import rate_limit
from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.notification import Notification
from app.models.publication import Publication
from app.models.user import User
from app.schemas.publication import (
    CommentCreate,
    CommentResponse,
    LikeResponse,
    PublicationCreate,
    PublicationResponse,
    PublicationUpdate,
    SaveResponse,
)
from app.services.publication_interaction_service import (
    build_publication_response,
    build_publication_responses,
    create_comment,
    delete_comment,
    get_comment,
    like_publication,
    list_comments,
    set_saved,
    unlike_publication,
    update_comment,
)
from app.services.publication_service import (
    can_user_view_publication,
    create_publication,
    delete_publication,
    get_accepted_contact_ids,
    get_publication_by_id,
    list_publications,
    update_publication,
)

router = APIRouter(prefix="/publications", tags=["Publications"])


def _get_full_name(user: User) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()

    if full_name:
        return full_name

    return user.email


def _get_publication_notification_type(
    publication_data: PublicationCreate,
) -> str:
    if publication_data.type in ["internship", "job", "social_service", "freelance"]:
        return "opportunity"

    return "publication"


@router.post(
    "",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("publication", 10, 600))],
)
async def create_publication_endpoint(
    publication_data: PublicationCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PublicationResponse:
    # Empleos y pasantías solo desde cuentas de empresa (evita ofertas falsas).
    if publication_data.type in JOB_TYPES and current_user.account_type != "company":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo las cuentas de empresa pueden publicar empleos y "
            "pasantías. Cámbiala en Configuración.",
        )

    publication = await create_publication(
        session=session,
        author_id=current_user.id,
        publication_data=publication_data,
        commit=False,
    )

    if publication.visibility != "private":
        contact_ids = await get_accepted_contact_ids(
            session=session,
            user_id=current_user.id,
        )

        notification_type = _get_publication_notification_type(publication_data)
        author_name = _get_full_name(current_user)

        if notification_type == "opportunity":
            title = "Nueva oportunidad"
            message = f"{author_name} publicó una nueva oportunidad."
        else:
            title = "Nueva publicación"
            message = f"{author_name} hizo una nueva publicación."

        for contact_id in contact_ids:
            notification = Notification(
                user_id=contact_id,
                type=notification_type,
                title=title,
                message=message,
                related_user_id=current_user.id,
                related_publication_id=publication.id,
                is_read=False,
            )

            session.add(notification)

        await notify_job_alerts(session, publication, _get_full_name(current_user))

    await session.commit()

    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author))
        .where(Publication.id == publication.id)
    )

    created_publication = result.scalar_one()

    return await build_publication_response(
        session, created_publication, current_user.id
    )


@router.get(
    "",
    response_model=list[PublicationResponse],
)
async def list_publications_endpoint(
    publication_type: str | None = Query(default=None, alias="type"),
    mine: bool = Query(default=False, description="Solo mis publicaciones"),
    saved: bool = Query(default=False, description="Solo las que guardé"),
    author_id: uuid.UUID | None = Query(default=None, alias="author"),
    q: str | None = Query(default=None, max_length=100, description="Buscar"),
    modality: str | None = Query(default=None, max_length=20),
    location: str | None = Query(default=None, max_length=120),
    opportunities: bool = Query(
        default=False, description="Solo empleos, pasantías, servicio social…"
    ),
    verified: bool = Query(default=False, description="Solo empresas verificadas"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[PublicationResponse]:
    publications = await list_publications(
        session=session,
        current_user_id=current_user.id,
        publication_type=publication_type,
        only_mine=mine,
        only_saved=saved,
        author_id=author_id,
        search=q,
        modality=modality,
        location=location,
        opportunities_only=opportunities,
        verified_only=verified,
        limit=limit,
        offset=offset,
    )

    return await build_publication_responses(session, publications, current_user.id)


@router.get(
    "/{publication_id}",
    response_model=PublicationResponse,
)
async def get_publication_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PublicationResponse:
    publication = await get_publication_by_id(
        session=session,
        publication_id=publication_id,
    )

    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    can_view = await can_user_view_publication(
        session=session,
        publication=publication,
        user_id=current_user.id,
    )

    if not can_view:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    return await build_publication_response(session, publication, current_user.id)


@router.patch(
    "/{publication_id}",
    response_model=PublicationResponse,
)
async def update_publication_endpoint(
    publication_id: uuid.UUID,
    publication_data: PublicationUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PublicationResponse:
    publication = await get_publication_by_id(
        session=session,
        publication_id=publication_id,
    )

    if publication is None or not publication.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    if publication.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own publications",
        )

    updated = await update_publication(
        session=session,
        publication=publication,
        publication_data=publication_data,
    )

    return await build_publication_response(session, updated, current_user.id)


@router.delete(
    "/{publication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_publication_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    publication = await get_publication_by_id(
        session=session,
        publication_id=publication_id,
    )

    if publication is None or not publication.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    if publication.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own publications",
        )

    await delete_publication(
        session=session,
        publication=publication,
    )


# =====================================================
# ME GUSTA Y COMENTARIOS
# =====================================================
async def _get_visible_publication(
    session: AsyncSession,
    publication_id: uuid.UUID,
    user: User,
) -> Publication:
    publication = await get_publication_by_id(
        session=session,
        publication_id=publication_id,
    )

    if publication is None or not await can_user_view_publication(
        session=session,
        publication=publication,
        user_id=user.id,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    return publication


@router.put("/{publication_id}/save", response_model=SaveResponse)
async def save_publication_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SaveResponse:
    publication = await _get_visible_publication(session, publication_id, current_user)
    await set_saved(session, publication, current_user, saved=True)
    return SaveResponse(saved=True)


@router.delete("/{publication_id}/save", response_model=SaveResponse)
async def unsave_publication_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SaveResponse:
    # Quitar no exige poder verla: si el autor la ocultó, igual se puede quitar.
    publication = await get_publication_by_id(
        session=session, publication_id=publication_id
    )
    if publication is not None:
        await set_saved(session, publication, current_user, saved=False)
    return SaveResponse(saved=False)


@router.post("/{publication_id}/like", response_model=LikeResponse)
async def like_publication_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> LikeResponse:
    publication = await _get_visible_publication(session, publication_id, current_user)
    likes = await like_publication(session, publication, current_user)
    return LikeResponse(liked=True, likes_count=likes)


@router.delete("/{publication_id}/like", response_model=LikeResponse)
async def unlike_publication_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> LikeResponse:
    publication = await _get_visible_publication(session, publication_id, current_user)
    likes = await unlike_publication(session, publication, current_user)
    return LikeResponse(liked=False, likes_count=likes)


@router.get("/{publication_id}/comments", response_model=list[CommentResponse])
async def list_comments_endpoint(
    publication_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[CommentResponse]:
    publication = await _get_visible_publication(session, publication_id, current_user)
    return await list_comments(
        session, publication, current_user.id, limit=limit, offset=offset
    )


@router.post(
    "/{publication_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("comment", 30, 60))],
)
async def create_comment_endpoint(
    publication_id: uuid.UUID,
    comment_data: CommentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CommentResponse:
    publication = await _get_visible_publication(session, publication_id, current_user)
    return await create_comment(session, publication, current_user, comment_data.text)


@router.patch(
    "/{publication_id}/comments/{comment_id}",
    response_model=CommentResponse,
)
async def update_comment_endpoint(
    publication_id: uuid.UUID,
    comment_id: uuid.UUID,
    comment_data: CommentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CommentResponse:
    publication = await _get_visible_publication(session, publication_id, current_user)
    comment = await get_comment(session, publication.id, comment_id)

    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comentario no encontrado.",
        )

    if comment.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes editar tus propios comentarios.",
        )

    return await update_comment(
        session,
        comment,
        comment_data.text,
        current_user_id=current_user.id,
        publication_author_id=publication.author_id,
    )


@router.delete(
    "/{publication_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment_endpoint(
    publication_id: uuid.UUID,
    comment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    publication = await _get_visible_publication(session, publication_id, current_user)
    comment = await get_comment(session, publication.id, comment_id)

    if comment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comentario no encontrado.",
        )

    # Lo borra quien lo escribió o el autor de la publicación (moderación).
    if current_user.id not in (comment.author_id, publication.author_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puedes eliminar este comentario.",
        )

    await delete_comment(session, comment)
