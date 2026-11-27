import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.user import User
from app.services.security import decode_access_token
from app.services.user_service import get_user_by_id


bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="Token JWT obtenido mediante POST /auth/login",
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No fue posible validar las credenciales.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError, TypeError):
        raise credentials_exception from None

    user = await get_user_by_id(
        session=session,
        user_id=user_id,
    )

    if user is None or not user.is_active:
        raise credentials_exception

    return user


_optional_bearer = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    session: AsyncSession = Depends(get_db_session),
) -> User | None:
    """El usuario si mandó un token válido; si no, None (sin error)."""
    if credentials is None:
        return None
    try:
        user_id = uuid.UUID(decode_access_token(credentials.credentials)["sub"])
    except (ValueError, KeyError, TypeError):
        return None
    user = await get_user_by_id(session=session, user_id=user_id)
    return user if user is not None and user.is_active else None
