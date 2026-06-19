import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.refresh_token import RefreshToken
from app.services.security import (
    create_refresh_token,
    generate_jti,
    hash_token,
)


async def create_user_refresh_token(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> str:
    jti = generate_jti()

    expires_at = datetime.now(UTC) + timedelta(
        days=settings.refresh_token_expire_days,
    )

    refresh_token = create_refresh_token(
        subject=str(user_id),
        jti=jti,
        expires_at=expires_at,
    )

    token_record = RefreshToken(
        user_id=user_id,
        jti=jti,
        token_hash=hash_token(refresh_token),
        expires_at=expires_at,
    )

    session.add(token_record)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return refresh_token


async def get_valid_refresh_token(
    session: AsyncSession,
    jti: str,
    raw_token: str,
) -> RefreshToken | None:
    statement = select(RefreshToken).where(
        RefreshToken.jti == jti,
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > datetime.now(UTC),
    )

    result = await session.execute(statement)
    token_record = result.scalar_one_or_none()

    if token_record is None:
        return None

    if token_record.token_hash != hash_token(raw_token):
        return None

    return token_record


async def revoke_refresh_token(
    session: AsyncSession,
    token_record: RefreshToken,
) -> None:
    token_record.revoked_at = datetime.now(UTC)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def revoke_all_user_refresh_tokens(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> None:
    statement = (
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )

    try:
        await session.execute(statement)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
