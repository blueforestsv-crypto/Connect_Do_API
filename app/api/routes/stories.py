"""Historias (estados) de 24 horas. Solo las ven la persona y sus contactos."""

import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.social import Follow
from app.models.social import HighlightItem
from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.story import Story, StoryView
from app.models.user import User
from app.services import media_service
from app.services.publication_service import get_accepted_contact_ids

router = APIRouter(prefix="/stories", tags=["Stories"])

STORY_HOURS = 24
_cleanup_tasks: set[asyncio.Task] = set()


# =====================================================
# ESQUEMAS
# =====================================================
class StoryCreate(BaseModel):
    type: Literal["image", "video"]
    url: str = Field(max_length=500)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    duration: float | None = Field(default=None, ge=0, le=60)
    caption: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def check_url(self) -> "StoryCreate":
        if not media_service.is_own_url(self.url):
            raise ValueError("El archivo debe subirse con la app.")
        return self


class StoryUser(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    profile_image_base64: str | None = None


class StoryItem(BaseModel):
    id: uuid.UUID
    type: str
    url: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    caption: str | None = None
    created_at: datetime
    expires_at: datetime
    viewed: bool = False
    # Solo en mis historias.
    views_count: int | None = None


class StoryGroup(BaseModel):
    user: StoryUser
    is_me: bool
    has_unseen: bool
    stories: list[StoryItem]


class StoryViewer(BaseModel):
    user: StoryUser
    viewed_at: datetime


def _user(user: User) -> StoryUser:
    profile = user.__dict__.get("profile")
    return StoryUser(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        profile_image_base64=profile.profile_image_base64 if profile else None,
    )


def _now() -> datetime:
    return datetime.now(UTC)


# =====================================================
# LIMPIEZA DE VENCIDAS
# =====================================================
_last_cleanup = 0.0
_CLEANUP_EVERY_SECONDS = 600


async def _delete_expired(session: AsyncSession) -> None:
    """Borra historias vencidas (como mucho cada 10 min) y luego sus archivos
    en Cloudinary. Usa la misma sesión de la petición."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < _CLEANUP_EVERY_SECONDS:
        return
    _last_cleanup = now

    result = await session.execute(
        select(Story.id, Story.media_url).where(Story.expires_at < _now()).limit(50)
    )
    rows = result.all()
    if not rows:
        return
    await session.execute(delete(Story).where(Story.id.in_([r[0] for r in rows])))
    await session.commit()

    # Las que están en destacadas conservan su archivo.
    kept = set(
        (
            await session.execute(
                select(HighlightItem.media_url).where(
                    HighlightItem.media_url.in_([r[1] for r in rows])
                )
            )
        )
        .scalars()
        .all()
    )
    task = asyncio.get_running_loop().create_task(
        media_service.destroy([r[1] for r in rows if r[1] not in kept])
    )
    _cleanup_tasks.add(task)
    task.add_done_callback(_cleanup_tasks.discard)


# =====================================================
# RUTAS
# =====================================================
@router.post("", response_model=StoryItem, status_code=status.HTTP_201_CREATED)
async def create_story(
    data: StoryCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> StoryItem:
    caption = (data.caption or "").strip() or None
    story = Story(
        user_id=current_user.id,
        media_type=data.type,
        media_url=data.url,
        width=data.width,
        height=data.height,
        duration=data.duration,
        caption=caption,
        expires_at=_now() + timedelta(hours=STORY_HOURS),
    )
    session.add(story)
    await session.commit()
    await session.refresh(story)
    return StoryItem(
        id=story.id,
        type=story.media_type,
        url=story.media_url,
        width=story.width,
        height=story.height,
        duration=story.duration,
        caption=story.caption,
        created_at=story.created_at,
        expires_at=story.expires_at,
        viewed=True,
        views_count=0,
    )


@router.get("", response_model=list[StoryGroup], summary="Historias activas")
async def list_stories(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[StoryGroup]:
    await _delete_expired(session)

    author_ids = [
        current_user.id,
        *await get_accepted_contact_ids(session, current_user.id),
        # Personas que sigo y que comparten sus historias con seguidores.
        *(
            await session.execute(
                select(User.id)
                .join(Follow, Follow.followed_id == User.id)
                .where(
                    Follow.follower_id == current_user.id,
                    User.story_privacy == "followers",
                )
            )
        ).scalars(),
    ]
    result = await session.execute(
        select(Story)
        .options(selectinload(Story.user).selectinload(User.profile))
        .where(Story.user_id.in_(author_ids), Story.expires_at > _now())
        .order_by(Story.created_at)
    )
    stories = list(result.scalars().all())
    if not stories:
        return []

    ids = [story.id for story in stories]
    seen = set(
        (
            await session.execute(
                select(StoryView.story_id).where(
                    StoryView.story_id.in_(ids),
                    StoryView.viewer_id == current_user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    mine = [story.id for story in stories if story.user_id == current_user.id]
    counts = (
        dict(
            (
                await session.execute(
                    select(StoryView.story_id, func.count())
                    .where(StoryView.story_id.in_(mine))
                    .group_by(StoryView.story_id)
                )
            ).all()
        )
        if mine
        else {}
    )

    groups: dict[uuid.UUID, StoryGroup] = {}
    for story in stories:
        is_me = story.user_id == current_user.id
        group = groups.setdefault(
            story.user_id,
            StoryGroup(
                user=_user(story.user), is_me=is_me, has_unseen=False, stories=[]
            ),
        )
        viewed = is_me or story.id in seen
        group.stories.append(
            StoryItem(
                id=story.id,
                type=story.media_type,
                url=story.media_url,
                width=story.width,
                height=story.height,
                duration=story.duration,
                caption=story.caption,
                created_at=story.created_at,
                expires_at=story.expires_at,
                viewed=viewed,
                views_count=counts.get(story.id, 0) if is_me else None,
            )
        )
        if not viewed:
            group.has_unseen = True

    # Yo primero; luego quien tiene historias sin ver; luego la más reciente.
    return sorted(
        groups.values(),
        key=lambda g: (
            not g.is_me,
            not g.has_unseen,
            -g.stories[-1].created_at.timestamp(),
        ),
    )


async def _visible_story(
    session: AsyncSession, story_id: uuid.UUID, user: User
) -> Story:
    story = await session.get(Story, story_id)
    if story is None or story.expires_at <= _now():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La historia ya no existe.")
    if story.user_id != user.id and not await _can_see_stories_of(
        session, user.id, story.user_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La historia ya no existe.")
    return story


async def _can_see_stories_of(
    session: AsyncSession, viewer_id: uuid.UUID, author_id: uuid.UUID
) -> bool:
    if author_id in await get_accepted_contact_ids(session, viewer_id):
        return True
    author = await session.get(User, author_id)
    if author is None or author.story_privacy != "followers":
        return False
    follows = await session.get(Follow, (viewer_id, author_id))
    return follows is not None


@router.post("/{story_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def view_story(
    story_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    story = await _visible_story(session, story_id, current_user)
    if story.user_id == current_user.id:
        return
    await session.execute(
        insert(StoryView)
        .values(story_id=story.id, viewer_id=current_user.id)
        .on_conflict_do_nothing()
    )
    await session.commit()


@router.get("/{story_id}/viewers", response_model=list[StoryViewer])
async def story_viewers(
    story_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[StoryViewer]:
    story = await _visible_story(session, story_id, current_user)
    if story.user_id != current_user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo puedes ver quién vio tus historias."
        )
    result = await session.execute(
        select(StoryView)
        .options(selectinload(StoryView.viewer).selectinload(User.profile))
        .where(StoryView.story_id == story.id)
        .order_by(StoryView.viewed_at.desc())
    )
    return [
        StoryViewer(user=_user(view.viewer), viewed_at=view.viewed_at)
        for view in result.scalars().all()
    ]


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story(
    story_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    story = await session.get(Story, story_id)
    if story is None or story.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La historia no existe.")
    url = story.media_url
    await session.delete(story)
    await session.commit()
    in_highlight = (
        await session.execute(
            select(HighlightItem.id).where(HighlightItem.media_url == url).limit(1)
        )
    ).first()
    if in_highlight is None:
        await media_service.destroy([url])
