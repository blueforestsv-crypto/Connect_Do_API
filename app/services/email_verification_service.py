"""Códigos de un solo uso enviados por correo.

Un mismo mecanismo sirve para tres propósitos:
- verify_email: confirmar el correo al registrarse.
- password_reset: restablecer la contraseña olvidada.
- email_change: confirmar un correo nuevo (se guarda en new_email).

Cada código vence, admite pocos intentos y anula a los anteriores del mismo
usuario y propósito.
"""

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

VERIFY_EMAIL = "verify_email"
PASSWORD_RESET = "password_reset"
EMAIL_CHANGE = "email_change"


def _hash_code(token_id: uuid.UUID, code: str) -> str:
    # El id del registro actúa como sal: dos usuarios con el mismo código
    # no generan el mismo hash (token_hash es único).
    return hash_token(f"{token_id}:{code}")


def _generate_code() -> str:
    length = settings.email_verification_code_length
    return f"{secrets.randbelow(10**length):0{length}d}"


async def can_issue_code(
    session: AsyncSession,
    user_id: uuid.UUID,
    purpose: str = VERIFY_EMAIL,
) -> bool:
    """Respeta la espera mínima entre reenvíos."""
    result = await session.execute(
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.purpose == purpose,
        )
        .order_by(EmailVerificationToken.created_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()

    if latest is None:
        return True

    resend_at = latest.created_at + timedelta(
        seconds=settings.email_verification_resend_seconds,
    )
    return datetime.now(UTC) >= resend_at


async def create_code(
    session: AsyncSession,
    user: User,
    purpose: str = VERIFY_EMAIL,
    new_email: str | None = None,
) -> str:
    """Anula los códigos pendientes del mismo propósito y emite uno nuevo."""
    code = _generate_code()
    now = datetime.now(UTC)

    revoke = (
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.purpose == purpose,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )

    token_id = uuid.uuid4()
    record = EmailVerificationToken(
        id=token_id,
        user_id=user.id,
        token_hash=_hash_code(token_id, code),
        purpose=purpose,
        new_email=new_email,
        expires_at=now
        + timedelta(minutes=settings.email_verification_token_expire_minutes),
    )

    try:
        await session.execute(revoke)
        session.add(record)
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    return code


async def consume_code(
    session: AsyncSession,
    user: User,
    code: str,
    purpose: str = VERIFY_EMAIL,
) -> EmailVerificationToken | None:
    """Valida el código vigente. Si es correcto lo marca como usado (sin hacer
    commit: quien llama aplica su cambio y confirma todo junto). Si no, suma
    un intento fallido y, al llegar al máximo, anula el código."""
    now = datetime.now(UTC)

    result = await session.execute(
        select(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.purpose == purpose,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.revoked_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .order_by(EmailVerificationToken.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    record = result.scalar_one_or_none()

    if record is None or not user.is_active:
        return None

    if not hmac.compare_digest(_hash_code(record.id, code.strip()), record.token_hash):
        record.failed_attempts += 1
        if record.failed_attempts >= settings.email_verification_max_attempts:
            record.revoked_at = now
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return None

    record.used_at = now
    return record


# =====================================================
# VERIFICACIÓN DE CORREO (nombres usados por las rutas existentes)
# =====================================================
async def can_issue_verification_token(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> bool:
    return await can_issue_code(session, user_id, VERIFY_EMAIL)


async def create_email_verification_code(
    session: AsyncSession,
    user: User,
) -> str:
    return await create_code(session, user, VERIFY_EMAIL)


async def confirm_email_verification_code(
    session: AsyncSession,
    user: User,
    code: str,
) -> bool:
    record = await consume_code(session, user, code, VERIFY_EMAIL)
    if record is None:
        return False

    user.is_verified = True
    try:
        await session.commit()
        await session.refresh(user)
    except Exception:
        await session.rollback()
        raise
    return True
