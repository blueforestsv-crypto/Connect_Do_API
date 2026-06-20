import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.services.security import hash_token


async def can_issue_verification_token(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> bool:
    statement = (
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user_id,
        )
        .order_by(EmailVerificationToken.created_at.desc())
        .limit(1)
    )

    result = await session.execute(statement)
    latest_token = result.scalar_one_or_none()

    if latest_token is None:
        return True

    resend_available_at = latest_token.created_at + timedelta(
        seconds=settings.email_verification_resend_seconds,
    )

    return datetime.now(UTC) >= resend_available_at


async def create_email_verification_token(
    session: AsyncSession,
    user: User,
) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hash_token(raw_token)

    now = datetime.now(UTC)
    expires_at = now + timedelta(
        minutes=settings.email_verification_token_expire_minutes,
    )

    revoke_statement = (
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    token_record = EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    try:
        await session.execute(revoke_statement)
        session.add(token_record)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return raw_token


async def confirm_email_verification(
    session: AsyncSession,
    raw_token: str,
) -> User | None:
    now = datetime.now(UTC)
    token_hash = hash_token(raw_token)

    statement = select(EmailVerificationToken).where(
        EmailVerificationToken.token_hash == token_hash,
        EmailVerificationToken.used_at.is_(None),
        EmailVerificationToken.revoked_at.is_(None),
        EmailVerificationToken.expires_at > now,
    )

    result = await session.execute(statement)
    token_record = result.scalar_one_or_none()

    if token_record is None:
        return None

    user = await session.get(
        User,
        token_record.user_id,
    )

    if user is None or not user.is_active:
        return None

    token_record.used_at = now
    user.is_verified = True

    revoke_other_tokens = (
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.id != token_record.id,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    try:
        await session.execute(revoke_other_tokens)
        await session.commit()
        await session.refresh(user)
    except Exception:
        await session.rollback()
        raise

    return user
