"""Me gusta y comentarios de publicaciones."""

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.safety_service import blocked_ids_query
from app.models.notification import Notification
from app.models.publication import Publication
from app.models.publication_interaction import (
    PublicationComment,
    PublicationLike,
    PublicationSave,
)
from app.models.user import User
from app.schemas.publication import CommentResponse, PublicationResponse


# =====================================================
# CONTADORES PARA EL FEED
# =====================================================
async def build_publication_responses(
    session: AsyncSession,
    publications: Sequence[Publication],
    current_user_id: uuid.UUID,
) -> list[PublicationResponse]:
    """Agrega likes, comentarios, liked_by_me e is_mine en 3 consultas,
    sin importar cuántas publicaciones haya."""
    if not publications:
        return []

    ids = [publication.id for publication in publications]

    likes_result = await session.execute(
        select(PublicationLike.publication_id, func.count())
        .where(PublicationLike.publication_id.in_(ids))
        .group_by(PublicationLike.publication_id)
    )
    likes_count = dict(likes_result.all())

    comments_result = await session.execute(
        select(PublicationComment.publication_id, func.count())
        .where(PublicationComment.publication_id.in_(ids))
        .group_by(PublicationComment.publication_id)
    )
    comments_count = dict(comments_result.all())

    liked_result = await session.execute(
        select(PublicationLike.publication_id).where(
            PublicationLike.publication_id.in_(ids),
            PublicationLike.user_id == current_user_id,
        )
    )
    liked_ids = set(liked_result.scalars().all())

    saved_result = await session.execute(
        select(PublicationSave.publication_id).where(
            PublicationSave.publication_id.in_(ids),
            PublicationSave.user_id == current_user_id,
        )
    )
    saved_ids = set(saved_result.scalars().all())

    responses: list[PublicationResponse] = []
    for publication in publications:
        response = PublicationResponse.model_validate(publication)
        response.likes_count = likes_count.get(publication.id, 0)
        response.comments_count = comments_count.get(publication.id, 0)
        response.liked_by_me = publication.id in liked_ids
        response.saved_by_me = publication.id in saved_ids
        response.is_mine = publication.author_id == current_user_id
        responses.append(response)

    return responses


async def build_publication_response(
    session: AsyncSession,
    publication: Publication,
    current_user_id: uuid.UUID,
) -> PublicationResponse:
    responses = await build_publication_responses(
        session, [publication], current_user_id
    )
    return responses[0]


# =====================================================
# GUARDADAS
# =====================================================
async def set_saved(
    session: AsyncSession,
    publication: Publication,
    user: User,
    saved: bool,
) -> None:
    if saved:
        await session.execute(
            insert(PublicationSave)
            .values(publication_id=publication.id, user_id=user.id)
            .on_conflict_do_nothing()
        )
    else:
        await session.execute(
            delete(PublicationSave).where(
                PublicationSave.publication_id == publication.id,
                PublicationSave.user_id == user.id,
            )
        )
    await session.commit()


# =====================================================
# ME GUSTA
# =====================================================
async def count_likes(session: AsyncSession, publication_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).where(PublicationLike.publication_id == publication_id)
    )
    return result.scalar_one()


async def like_publication(
    session: AsyncSession,
    publication: Publication,
    user: User,
) -> int:
    # Idempotente: un segundo "me gusta" no hace nada.
    result = await session.execute(
        insert(PublicationLike)
        .values(publication_id=publication.id, user_id=user.id)
        .on_conflict_do_nothing()
    )

    if result.rowcount and publication.author_id != user.id:
        await _notify_once(
            session,
            recipient_id=publication.author_id,
            actor=user,
            publication=publication,
            notification_type="like",
            title="Nuevo me gusta",
            message=f"A {_full_name(user)} le gusta tu publicación.",
        )

    await session.commit()
    return await count_likes(session, publication.id)


async def unlike_publication(
    session: AsyncSession,
    publication: Publication,
    user: User,
) -> int:
    await session.execute(
        delete(PublicationLike).where(
            PublicationLike.publication_id == publication.id,
            PublicationLike.user_id == user.id,
        )
    )
    await session.commit()
    return await count_likes(session, publication.id)


# =====================================================
# COMENTARIOS
# =====================================================
def _comment_response(
    comment: PublicationComment,
    current_user_id: uuid.UUID,
    publication_author_id: uuid.UUID,
) -> CommentResponse:
    response = CommentResponse.model_validate(comment)
    response.is_mine = comment.author_id == current_user_id
    response.can_delete = response.is_mine or publication_author_id == current_user_id
    return response


async def list_comments(
    session: AsyncSession,
    publication: Publication,
    current_user_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[CommentResponse]:
    result = await session.execute(
        select(PublicationComment)
        .options(selectinload(PublicationComment.author).selectinload(User.profile))
        .where(
            PublicationComment.publication_id == publication.id,
            PublicationComment.author_id.not_in(blocked_ids_query(current_user_id)),
        )
        .order_by(PublicationComment.created_at.asc(), PublicationComment.id.asc())
        .limit(limit)
        .offset(offset)
    )

    return [
        _comment_response(comment, current_user_id, publication.author_id)
        for comment in result.scalars().all()
    ]


async def get_comment(
    session: AsyncSession,
    publication_id: uuid.UUID,
    comment_id: uuid.UUID,
) -> PublicationComment | None:
    result = await session.execute(
        select(PublicationComment)
        .options(selectinload(PublicationComment.author).selectinload(User.profile))
        .where(
            PublicationComment.id == comment_id,
            PublicationComment.publication_id == publication_id,
        )
    )
    return result.scalar_one_or_none()


async def create_comment(
    session: AsyncSession,
    publication: Publication,
    user: User,
    text: str,
) -> CommentResponse:
    comment = PublicationComment(
        publication_id=publication.id,
        author_id=user.id,
        text=text,
    )
    session.add(comment)

    if publication.author_id != user.id:
        session.add(
            Notification(
                user_id=publication.author_id,
                type="comment",
                title="Nuevo comentario",
                message=f"{_full_name(user)} comentó: {_preview(text)}",
                related_user_id=user.id,
                related_publication_id=publication.id,
                is_read=False,
            )
        )

    await session.commit()

    created = await get_comment(session, publication.id, comment.id)
    assert created is not None
    return _comment_response(created, user.id, publication.author_id)


async def update_comment(
    session: AsyncSession,
    comment: PublicationComment,
    text: str,
    current_user_id: uuid.UUID,
    publication_author_id: uuid.UUID,
) -> CommentResponse:
    comment.text = text
    await session.commit()

    updated = await get_comment(session, comment.publication_id, comment.id)
    assert updated is not None
    return _comment_response(updated, current_user_id, publication_author_id)


async def delete_comment(session: AsyncSession, comment: PublicationComment) -> None:
    await session.delete(comment)
    await session.commit()


# =====================================================
# AUXILIARES
# =====================================================
def _full_name(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.email


def _preview(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


async def _notify_once(
    session: AsyncSession,
    *,
    recipient_id: uuid.UUID,
    actor: User,
    publication: Publication,
    notification_type: str,
    title: str,
    message: str,
) -> None:
    """Evita llenar de avisos al autor si alguien da y quita "me gusta"
    varias veces: solo uno sin leer por persona y publicación."""
    existing = await session.execute(
        select(Notification.id).where(
            and_(
                Notification.user_id == recipient_id,
                Notification.related_user_id == actor.id,
                Notification.related_publication_id == publication.id,
                Notification.type == notification_type,
                Notification.is_read.is_(False),
            )
        )
    )

    if existing.first() is not None:
        return

    session.add(
        Notification(
            user_id=recipient_id,
            type=notification_type,
            title=title,
            message=message,
            related_user_id=actor.id,
            related_publication_id=publication.id,
            is_read=False,
        )
    )
