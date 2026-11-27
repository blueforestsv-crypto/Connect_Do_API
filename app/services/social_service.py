"""Menciones (@) y seguidores."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.social import Follow
from app.models.user import User
from app.services.safety_service import blocked_ids

MAX_MENTIONS = 10


def _name(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or "Usuario"


async def resolve_mentions(
    session: AsyncSession, ids: list[uuid.UUID], author: User
) -> list[dict]:
    """[{id, name}] de las personas mencionadas que existen, están activas y
    no tienen bloqueo con el autor."""
    unique = [i for i in dict.fromkeys(ids) if i != author.id][:MAX_MENTIONS]
    if not unique:
        return []
    blocked = await blocked_ids(session, author.id)
    result = await session.execute(
        select(User).where(User.id.in_(unique), User.is_active.is_(True))
    )
    users = {user.id: user for user in result.scalars().all()}
    return [
        {"id": str(i), "name": _name(users[i])}
        for i in unique
        if i in users and i not in blocked
    ]


def notify_mentions(
    session: AsyncSession,
    mentions: list[dict],
    author: User,
    publication_id: uuid.UUID,
    where: str,
) -> None:
    """[where]: "una publicación" o "un comentario". Sin commit."""
    for mention in mentions:
        session.add(
            Notification(
                user_id=uuid.UUID(mention["id"]),
                type="mention",
                title="Te mencionaron",
                message=f"{_name(author)} te mencionó en {where}.",
                related_user_id=author.id,
                related_publication_id=publication_id,
                is_read=False,
            )
        )


async def follow_counts(
    session: AsyncSession, user_id: uuid.UUID, viewer_id: uuid.UUID
) -> dict:
    followers = (
        await session.execute(
            select(func.count()).select_from(Follow).where(Follow.followed_id == user_id)
        )
    ).scalar_one()
    following = (
        await session.execute(
            select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
        )
    ).scalar_one()
    is_following = False
    follows_me = False
    if viewer_id != user_id:
        rows = await session.execute(
            select(Follow.follower_id).where(
                (
                    (Follow.follower_id == viewer_id)
                    & (Follow.followed_id == user_id)
                )
                | (
                    (Follow.follower_id == user_id)
                    & (Follow.followed_id == viewer_id)
                )
            )
        )
        for (follower,) in rows.all():
            if follower == viewer_id:
                is_following = True
            else:
                follows_me = True
    return {
        "followers_count": followers,
        "following_count": following,
        "is_following": is_following,
        "follows_me": follows_me,
    }
