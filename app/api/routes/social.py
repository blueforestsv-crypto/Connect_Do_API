"""Seguir, Explorar, sugerencias e historias destacadas."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db_session
from app.models.contact_request import ContactRequest
from app.models.notification import Notification
from app.models.profile import Profile
from app.models.publication import Publication
from app.models.publication_interaction import PublicationComment, PublicationLike
from app.models.social import Follow, Highlight, HighlightItem
from app.models.story import Story
from app.models.user import User
from app.schemas.publication import PublicationResponse
from app.services.people_service import get_contact_status
from app.services.publication_interaction_service import build_publication_responses
from app.services.publication_service import _private_author_ids
from app.services.safety_service import blocked_ids_query, is_blocked

router = APIRouter(tags=["Social"])

MAX_HIGHLIGHTS = 20
MAX_HIGHLIGHT_ITEMS = 50


# =====================================================
# ESQUEMAS
# =====================================================
class PersonCard(BaseModel):
    id: uuid.UUID
    name: str
    headline: str | None = None
    career: str | None = None
    university: str | None = None
    profile_image_base64: str | None = None
    account_type: str = "student"
    company_verified: bool = False
    is_following: bool = False
    # Por qué se sugiere ("Misma carrera", "Te sigue"…).
    reason: str | None = None


class HighlightItemOut(BaseModel):
    id: uuid.UUID
    type: str
    url: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    caption: str | None = None
    created_at: datetime


class HighlightOut(BaseModel):
    id: uuid.UUID
    title: str
    cover_url: str | None = None
    items: list[HighlightItemOut]


class HighlightCreate(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    story_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_HIGHLIGHT_ITEMS)


class HighlightAdd(BaseModel):
    story_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_HIGHLIGHT_ITEMS)


class ExploreOut(BaseModel):
    publications: list[PublicationResponse]
    people: list[PersonCard]


def _person(user: User, following: set[uuid.UUID], reason: str | None = None):
    profile = user.profile
    return PersonCard(
        id=user.id,
        name=f"{user.first_name} {user.last_name}".strip(),
        headline=profile.headline if profile else None,
        career=profile.career if profile else None,
        university=profile.university if profile else None,
        profile_image_base64=profile.profile_image_base64 if profile else None,
        account_type=user.account_type,
        company_verified=user.company_verified,
        is_following=user.id in following,
        reason=reason,
    )


async def _my_following(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await session.execute(
        select(Follow.followed_id).where(Follow.follower_id == user_id)
    )
    return set(rows.scalars().all())


# =====================================================
# SEGUIR
# =====================================================
@router.post(
    "/users/{user_id}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("follow", 60, 3600))],
)
async def follow(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No puedes seguirte.")
    target = await session.get(User, user_id)
    if (
        target is None
        or not target.is_active
        or await is_blocked(session, current_user.id, user_id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")

    result = await session.execute(
        insert(Follow)
        .values(follower_id=current_user.id, followed_id=user_id)
        .on_conflict_do_nothing()
    )
    if result.rowcount:
        session.add(
            Notification(
                user_id=user_id,
                type="follow",
                title="Nuevo seguidor",
                message=f"{current_user.first_name} {current_user.last_name}".strip()
                + " empezó a seguirte.",
                related_user_id=current_user.id,
                is_read=False,
            )
        )
    await session.commit()


@router.delete("/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.execute(
        delete(Follow).where(
            Follow.follower_id == current_user.id, Follow.followed_id == user_id
        )
    )
    await session.commit()


async def _follow_list(
    session: AsyncSession,
    user_id: uuid.UUID,
    viewer: User,
    followers: bool,
) -> list[PersonCard]:
    target = await session.get(User, user_id)
    if target is None or await is_blocked(session, viewer.id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    # Perfil privado: la lista solo la ven sus contactos.
    profile = (
        await session.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()
    if profile and profile.is_private and viewer.id != user_id:
        status_, _ = await get_contact_status(session, viewer.id, user_id)
        if status_ != "accepted":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta cuenta es privada.")

    join_col = Follow.follower_id if followers else Follow.followed_id
    where_col = Follow.followed_id if followers else Follow.follower_id
    result = await session.execute(
        select(User)
        .join(Follow, join_col == User.id)
        .options(selectinload(User.profile))
        .where(
            where_col == user_id,
            User.is_active.is_(True),
            User.id.not_in(blocked_ids_query(viewer.id)),
        )
        .order_by(Follow.created_at.desc())
        .limit(200)
    )
    following = await _my_following(session, viewer.id)
    return [_person(user, following) for user in result.scalars().all()]


@router.get("/users/{user_id}/followers", response_model=list[PersonCard])
async def followers(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[PersonCard]:
    return await _follow_list(session, user_id, current_user, followers=True)


@router.get("/users/{user_id}/following", response_model=list[PersonCard])
async def following(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[PersonCard]:
    return await _follow_list(session, user_id, current_user, followers=False)


# =====================================================
# EXPLORAR Y SUGERENCIAS
# =====================================================
async def suggestions(
    session: AsyncSession, user: User, limit: int = 15
) -> list[PersonCard]:
    """Personas que quizá conozcas: misma universidad o carrera, o que te
    siguen. Sin contactos, bloqueados ni a quienes ya sigues."""
    me = (
        await session.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalar_one_or_none()
    following = await _my_following(session, user.id)
    contacts = select(
        func.coalesce(
            func.nullif(ContactRequest.receiver_id, user.id),
            ContactRequest.requester_id,
        )
    ).where(
        or_(
            ContactRequest.requester_id == user.id,
            ContactRequest.receiver_id == user.id,
        ),
        ContactRequest.status.in_(("accepted", "pending")),
    )
    follows_me = select(Follow.follower_id).where(Follow.followed_id == user.id)

    affinity = []
    if me and me.career:
        affinity.append(Profile.career == me.career)
    if me and me.university:
        affinity.append(Profile.university == me.university)
    affinity.append(User.id.in_(follows_me))

    result = await session.execute(
        select(User)
        .join(Profile, Profile.user_id == User.id)
        .options(selectinload(User.profile))
        .where(
            User.id != user.id,
            User.is_active.is_(True),
            User.id.not_in(blocked_ids_query(user.id)),
            User.id.not_in(contacts),
            User.id.not_in(following or [uuid.uuid4()]),
            or_(*affinity),
        )
        .order_by(User.created_at.desc())
        .limit(limit)
    )
    follower_ids = set((await session.execute(follows_me)).scalars().all())

    cards = []
    for person in result.scalars().all():
        p = person.profile
        if person.id in follower_ids:
            reason = "Te sigue"
        elif me and p and me.career and p.career == me.career:
            reason = "Misma carrera"
        elif me and p and me.university and p.university == me.university:
            reason = f"También de {p.university}"
        else:
            reason = None
        cards.append(_person(person, following, reason))
    return cards


@router.get("/people/suggestions", response_model=list[PersonCard])
async def people_suggestions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[PersonCard]:
    return await suggestions(session, current_user)


@router.get(
    "/explore",
    response_model=ExploreOut,
    summary="Publicaciones populares y personas para descubrir",
)
async def explore(
    limit: int = Query(default=24, ge=1, le=60),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ExploreOut:
    since = datetime.now(UTC) - timedelta(days=21)
    likes = (
        select(func.count())
        .select_from(PublicationLike)
        .where(PublicationLike.publication_id == Publication.id)
        .scalar_subquery()
    )
    comments = (
        select(func.count())
        .select_from(PublicationComment)
        .where(PublicationComment.publication_id == Publication.id)
        .scalar_subquery()
    )
    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author).selectinload(User.profile))
        .where(
            Publication.is_active.is_(True),
            Publication.visibility == "public",
            Publication.created_at >= since,
            Publication.author_id != current_user.id,
            Publication.author_id.not_in(_private_author_ids()),
            Publication.author_id.not_in(blocked_ids_query(current_user.id)),
            Publication.author_id.not_in(
                select(User.id).where(User.is_active.is_(False))
            ),
        )
        # Lo más comentado y con más me gusta; las recientes desempatan.
        .order_by((likes + comments * 2).desc(), Publication.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    publications = await build_publication_responses(
        session, list(result.scalars().all()), current_user.id
    )
    people = await suggestions(session, current_user, limit=10) if offset == 0 else []
    return ExploreOut(publications=publications, people=people)


# =====================================================
# HISTORIAS DESTACADAS
# =====================================================
def _highlight_out(highlight: Highlight) -> HighlightOut:
    items = [
        HighlightItemOut(
            id=item.id,
            type=item.media_type,
            url=item.media_url,
            width=item.width,
            height=item.height,
            duration=item.duration,
            caption=item.caption,
            created_at=item.created_at,
        )
        for item in highlight.items
    ]
    return HighlightOut(
        id=highlight.id,
        title=highlight.title,
        cover_url=items[0].url if items else None,
        items=items,
    )


async def _copy_stories(
    session: AsyncSession, highlight: Highlight, story_ids: list[uuid.UUID], user: User
) -> int:
    result = await session.execute(
        select(Story).where(Story.id.in_(story_ids), Story.user_id == user.id)
    )
    stories = list(result.scalars().all())
    existing = {item.media_url for item in highlight.items}
    added = 0
    for story in stories:
        if story.media_url in existing:
            continue
        if len(highlight.items) >= MAX_HIGHLIGHT_ITEMS:
            break
        highlight.items.append(
            HighlightItem(
                media_type=story.media_type,
                media_url=story.media_url,
                width=story.width,
                height=story.height,
                duration=story.duration,
                caption=story.caption,
            )
        )
        added += 1
    return added


async def _get_highlight(
    session: AsyncSession, highlight_id: uuid.UUID
) -> Highlight | None:
    result = await session.execute(
        select(Highlight)
        .options(selectinload(Highlight.items))
        .where(Highlight.id == highlight_id)
    )
    return result.scalar_one_or_none()


@router.get("/users/{user_id}/highlights", response_model=list[HighlightOut])
async def list_highlights(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[HighlightOut]:
    if await is_blocked(session, current_user.id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    profile = (
        await session.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()
    if profile and profile.is_private and current_user.id != user_id:
        status_, _ = await get_contact_status(session, current_user.id, user_id)
        if status_ != "accepted":
            return []
    result = await session.execute(
        select(Highlight)
        .options(selectinload(Highlight.items))
        .where(Highlight.user_id == user_id)
        .order_by(Highlight.created_at.desc())
    )
    return [_highlight_out(h) for h in result.scalars().all() if h.items]


@router.post(
    "/highlights", response_model=HighlightOut, status_code=status.HTTP_201_CREATED
)
async def create_highlight(
    data: HighlightCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> HighlightOut:
    count = (
        await session.execute(
            select(func.count())
            .select_from(Highlight)
            .where(Highlight.user_id == current_user.id)
        )
    ).scalar_one()
    if count >= MAX_HIGHLIGHTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Puedes tener hasta {MAX_HIGHLIGHTS} destacadas.",
        )
    highlight = Highlight(user_id=current_user.id, title=data.title.strip())
    highlight.items = []
    session.add(highlight)
    if not await _copy_stories(session, highlight, data.story_ids, current_user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Elige una de tus historias.")
    await session.commit()
    created = await _get_highlight(session, highlight.id)
    return _highlight_out(created)


@router.post("/highlights/{highlight_id}/items", response_model=HighlightOut)
async def add_to_highlight(
    highlight_id: uuid.UUID,
    data: HighlightAdd,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> HighlightOut:
    highlight = await _get_highlight(session, highlight_id)
    if highlight is None or highlight.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe.")
    await _copy_stories(session, highlight, data.story_ids, current_user)
    await session.commit()
    return _highlight_out(await _get_highlight(session, highlight_id))


@router.delete("/highlights/{highlight_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_highlight(
    highlight_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.execute(
        delete(Highlight).where(
            Highlight.id == highlight_id, Highlight.user_id == current_user.id
        )
    )
    await session.commit()


@router.delete(
    "/highlights/{highlight_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_highlight_item(
    highlight_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    highlight = await session.get(Highlight, highlight_id)
    if highlight is None or highlight.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe.")
    await session.execute(
        delete(HighlightItem).where(
            and_(
                HighlightItem.id == item_id,
                HighlightItem.highlight_id == highlight_id,
            )
        )
    )
    await session.commit()
