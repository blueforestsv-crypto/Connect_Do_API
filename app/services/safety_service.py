"""Bloqueos: si A bloquea a B, ninguno ve el contenido del otro ni puede
escribirle (en ambos sentidos, como en Instagram)."""

import uuid

from sqlalchemy import or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.safety import UserBlock


def blocked_ids_query(user_id: uuid.UUID):
    """Subconsulta con los ids bloqueados por mí o que me bloquearon."""
    return union(
        select(UserBlock.blocked_id).where(UserBlock.blocker_id == user_id),
        select(UserBlock.blocker_id).where(UserBlock.blocked_id == user_id),
    ).scalar_subquery()


async def blocked_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    result = await session.execute(
        select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )
    ids: set[uuid.UUID] = set()
    for blocker, blocked in result.all():
        ids.add(blocked if blocker == user_id else blocker)
    return ids


async def is_blocked(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    if a == b:
        return False
    return b in await blocked_ids(session, a)
