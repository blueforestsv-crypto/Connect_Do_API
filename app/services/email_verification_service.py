import hmac
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


def _hash_code(token_id: uuid.UUID, code: str) -> str:
    # El id del registro actúa como sal: dos usuarios con el mismo código
    # no generan el mismo hash (token_hash es único).
    return hash_token(f"{token_id}:{code}")


def _generate_code() -> str:
    length = settings.email_verification_code_length
    return f"{secrets.randbelow(10**length):0{length}d}"


async def create_email_verification_code(
    session: AsyncSession,
    user: User,
) -> str:
    """Revoca los códigos pendientes del usuario y emite uno nuevo."""
    code = _generate_code()

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

    token_id = uuid.uuid4()
    token_record = EmailVerificationToken(
        id=token_id,
        user_id=user.id,
        token_hash=_hash_code(token_id, code),
        expires_at=expires_at,
    )

    try:
        await session.execute(revoke_statement)
        session.add(token_record)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return code


async def confirm_email_verification_code(
    session: AsyncSession,
    user: User,
    code: str,
) -> bool:
    """Valida el código vigente del usuario.

    Cada intento fallido suma al contador; al llegar al máximo el código
    se revoca y hay que solicitar uno nuevo.
    """
    now = datetime.now(UTC)

    statement = (
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.revoked_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .order_by(EmailVerificationToken.created_at.desc())
        .limit(1)
        .with_for_update()
    )

    result = await session.execute(statement)
    token_record = result.scalar_one_or_none()

    if token_record is None or not user.is_active:
        return False

    expected_hash = _hash_code(token_record.id, code.strip())

    try:
        if not hmac.compare_digest(expected_hash, token_record.token_hash):
            token_record.failed_attempts += 1

            if token_record.failed_attempts >= settings.email_verification_max_attempts:
                token_record.revoked_at = now

            await session.commit()
            return False

        token_record.used_at = now
        user.is_verified = True

        await session.commit()
        await session.refresh(user)
    except Exception:
        await session.rollback()
        raise

    return True
