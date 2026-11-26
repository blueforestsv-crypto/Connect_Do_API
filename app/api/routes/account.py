"""Gestión de la cuenta: recuperar y cambiar contraseña, cambiar correo."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import rate_limit
from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.account import (
    EmailChangeConfirm,
    EmailChangeRequest,
    MessageResponse,
    PasswordChangeRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from app.schemas.email_verification import EmailVerificationResponse
from app.schemas.user import UserResponse
from app.services.email_service import send_code_email
from app.services.email_verification_service import (
    EMAIL_CHANGE,
    PASSWORD_RESET,
    can_issue_code,
    consume_code,
    create_code,
)
from app.services.security import hash_password, verify_password
from app.services.session_service import revoke_all_user_refresh_tokens
from app.services.user_service import get_user_by_email

router = APIRouter(prefix="/auth", tags=["Account"])

INVALID_CODE = "El código es incorrecto o ha vencido. Solicita uno nuevo."


def _debug_code(code: str) -> str | None:
    """Solo en development sin proveedor de correo, para poder probar."""
    return code if settings.is_development and not settings.email_enabled else None


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


# =====================================================
# RECUPERAR CONTRASEÑA (sin sesión)
# =====================================================
@router.post(
    "/password-reset/request",
    response_model=EmailVerificationResponse,
    summary="Enviar código para restablecer la contraseña",
    dependencies=[Depends(rate_limit("reset_mail", 5, 600))],
)
async def request_password_reset(
    data: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> EmailVerificationResponse:
    # Mismo mensaje exista o no la cuenta, para no revelar correos.
    neutral = EmailVerificationResponse(
        message="Si el correo está registrado, te enviamos un código.",
    )

    user = await get_user_by_email(session=session, email=str(data.email))
    if user is None or not user.is_active:
        return neutral

    if not await can_issue_code(session, user.id, PASSWORD_RESET):
        return neutral

    code = await create_code(session, user, PASSWORD_RESET)
    background_tasks.add_task(send_code_email, user.email, code, PASSWORD_RESET)

    return EmailVerificationResponse(
        message=neutral.message,
        debug_code=_debug_code(code),
    )


@router.post(
    "/password-reset/confirm",
    response_model=MessageResponse,
    summary="Restablecer la contraseña con el código recibido",
    dependencies=[Depends(rate_limit("reset_confirm", 10, 600))],
)
async def confirm_password_reset(
    data: PasswordResetConfirm,
    session: AsyncSession = Depends(get_db_session),
) -> MessageResponse:
    user = await get_user_by_email(session=session, email=str(data.email))
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_CODE)

    record = await consume_code(session, user, data.code, PASSWORD_RESET)
    if record is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_CODE)

    user.hashed_password = hash_password(data.new_password)
    # Recibir el código prueba que la persona controla ese correo.
    user.is_verified = True
    await _commit(session)

    # Cierra las sesiones abiertas en otros dispositivos.
    await revoke_all_user_refresh_tokens(session=session, user_id=user.id)

    return MessageResponse(message="Tu contraseña se actualizó. Ya puedes entrar.")


# =====================================================
# CAMBIAR CONTRASEÑA (con sesión)
# =====================================================
@router.post(
    "/password/change",
    response_model=MessageResponse,
    summary="Cambiar la contraseña",
)
async def change_password(
    data: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> MessageResponse:
    if current_user.hashed_password is not None and not verify_password(
        plain_password=data.current_password or "",
        hashed_password=current_user.hashed_password,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La contraseña actual no es correcta.",
        )

    had_password = current_user.hashed_password is not None
    current_user.hashed_password = hash_password(data.new_password)
    await _commit(session)

    return MessageResponse(
        message=(
            "Contraseña actualizada."
            if had_password
            else "Listo: ahora también puedes entrar con tu correo y contraseña."
        )
    )


# =====================================================
# CAMBIAR CORREO (con sesión)
# =====================================================
@router.post(
    "/email-change/request",
    response_model=EmailVerificationResponse,
    summary="Enviar código al correo nuevo",
    dependencies=[Depends(rate_limit("email_change", 5, 600))],
)
async def request_email_change(
    data: EmailChangeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> EmailVerificationResponse:
    new_email = str(data.new_email).strip().lower()

    if new_email == current_user.email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ese ya es tu correo actual.",
        )

    if current_user.hashed_password is not None and not verify_password(
        plain_password=data.password or "",
        hashed_password=current_user.hashed_password,
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La contraseña no es correcta.",
        )

    if await get_user_by_email(session=session, email=new_email) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ese correo ya está en uso por otra cuenta.",
        )

    if not await can_issue_code(session, current_user.id, EMAIL_CHANGE):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Espera un minuto antes de pedir otro código.",
        )

    code = await create_code(session, current_user, EMAIL_CHANGE, new_email)
    background_tasks.add_task(send_code_email, new_email, code, EMAIL_CHANGE)

    return EmailVerificationResponse(
        message=f"Te enviamos un código a {new_email}.",
        debug_code=_debug_code(code),
    )


@router.post(
    "/email-change/confirm",
    response_model=UserResponse,
    summary="Confirmar el correo nuevo con el código",
)
async def confirm_email_change(
    data: EmailChangeConfirm,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    record = await consume_code(session, current_user, data.code, EMAIL_CHANGE)
    if record is None or not record.new_email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID_CODE)

    # Por si alguien tomó ese correo mientras tanto.
    taken = await get_user_by_email(session=session, email=record.new_email)
    if taken is not None and taken.id != current_user.id:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ese correo ya está en uso por otra cuenta.",
        )

    current_user.email = record.new_email
    current_user.is_verified = True
    await _commit(session)
    await session.refresh(current_user)

    return UserResponse.model_validate(current_user)
