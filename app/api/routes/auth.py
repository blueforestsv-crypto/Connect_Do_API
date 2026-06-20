import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.user import UserCreate, UserResponse
from app.services.security import (
    create_access_token,
    decode_refresh_token,
)
from app.services.session_service import (
    create_user_refresh_token,
    get_valid_refresh_token,
    revoke_refresh_token,
)
from app.services.user_service import (
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_by_id,
)

from app.core.config import settings
from app.schemas.email_verification import (
    EmailVerificationConfirm,
    EmailVerificationRequest,
    EmailVerificationResponse,
)
from app.services.email_service import send_verification_email
from app.services.email_verification_service import (
    can_issue_verification_token,
    confirm_email_verification,
    create_email_verification_token,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# =====================================================
# REGISTRAR USUARIO
# =====================================================
@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un nuevo usuario",
)
async def register_user(
    user_data: UserCreate,
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    existing_user = await get_user_by_email(
        session=session,
        email=str(user_data.email),
    )

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una cuenta registrada con este correo.",
        )

    user = await create_user(
        session=session,
        user_data=user_data,
    )

    return UserResponse.model_validate(user)


# =====================================================
# INICIAR SESIÓN
# =====================================================
@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Iniciar sesión",
)
async def login_user(
    login_data: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    user = await authenticate_user(
        session=session,
        email=str(login_data.email),
        password=login_data.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        subject=str(user.id),
    )

    refresh_token = await create_user_refresh_token(
        session=session,
        user_id=user.id,
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


# =====================================================
# RENOVAR ACCESS TOKEN
# =====================================================
@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    summary="Renovar token de acceso",
)
async def refresh_access_token(
    request_data: RefreshTokenRequest,
    session: AsyncSession = Depends(get_db_session),
) -> AccessTokenResponse:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token inválido o vencido.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_refresh_token(request_data.refresh_token)

        user_id = uuid.UUID(payload["sub"])
        jti = payload["jti"]

    except (ValueError, KeyError, TypeError):
        raise credentials_exception from None

    token_record = await get_valid_refresh_token(
        session=session,
        jti=jti,
        raw_token=request_data.refresh_token,
    )

    if token_record is None:
        raise credentials_exception

    user = await get_user_by_id(
        session=session,
        user_id=user_id,
    )

    if user is None or not user.is_active:
        raise credentials_exception

    access_token = create_access_token(
        subject=str(user.id),
    )

    return AccessTokenResponse(
        access_token=access_token,
    )


# =====================================================
# CERRAR SESIÓN
# =====================================================
@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cerrar sesión",
)
async def logout_user(
    request_data: LogoutRequest,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token inválido o vencido.",
    )

    try:
        payload = decode_refresh_token(request_data.refresh_token)
        jti = payload["jti"]

    except (ValueError, KeyError, TypeError):
        raise credentials_exception from None

    token_record = await get_valid_refresh_token(
        session=session,
        jti=jti,
        raw_token=request_data.refresh_token,
    )

    if token_record is None:
        raise credentials_exception

    await revoke_refresh_token(
        session=session,
        token_record=token_record,
    )


# =====================================================
# OBTENER USUARIO AUTENTICADO
# =====================================================
@router.get(
    "/me",
    response_model=UserResponse,
    summary="Obtener usuario autenticado",
)
async def get_authenticated_user(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)


## =====================================================
# VERIFICACIÓN DE CORREO
# =====================================================
@router.post(
    "/email-verification/request",
    response_model=EmailVerificationResponse,
    summary="Solicitar verificación de correo",
)
async def request_email_verification(
    request_data: EmailVerificationRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> EmailVerificationResponse:
    neutral_message = (
        "Si la cuenta existe y requiere verificación, "
        "se enviaron las instrucciones correspondientes."
    )

    user = await get_user_by_email(
        session=session,
        email=str(request_data.email),
    )

    if user is None or user.is_verified or not user.is_active:
        return EmailVerificationResponse(
            message=neutral_message,
        )

    can_issue = await can_issue_verification_token(
        session=session,
        user_id=user.id,
    )

    if not can_issue:
        return EmailVerificationResponse(
            message=neutral_message,
        )

    raw_token = await create_email_verification_token(
        session=session,
        user=user,
    )

    background_tasks.add_task(
        send_verification_email,
        recipient=user.email,
        token=raw_token,
    )

    return EmailVerificationResponse(
        message=neutral_message,
        debug_token=(raw_token if settings.app_env == "development" else None),
    )

    # =====================================================
    # CONFIRMAR VERIFICACIÓN DE CORREO
    # =====================================================


@router.post(
    "/email-verification/confirm",
    response_model=UserResponse,
    summary="Confirmar dirección de correo",
)
async def confirm_user_email(
    request_data: EmailVerificationConfirm,
    session: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    user = await confirm_email_verification(
        session=session,
        raw_token=request_data.token,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "El token de verificación es inválido, ya fue utilizado o ha vencido."
            ),
        )

    return UserResponse.model_validate(user)
