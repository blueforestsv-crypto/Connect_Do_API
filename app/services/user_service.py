from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.profile import Profile
from app.schemas.user import UserCreate
from app.services.security import hash_password
from app.services.security import verify_password
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.google_auth_service import GoogleIdentity


async def get_user_by_email(
    session: AsyncSession,
    email: str,
) -> User | None:
    normalized_email = email.strip().lower()

    statement = select(User).where(User.email == normalized_email)
    result = await session.execute(statement)

    return result.scalar_one_or_none()


async def get_user_by_id(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> User | None:
    return await session.get(User, user_id)


async def create_user(
    session: AsyncSession,
    user_data: UserCreate,
) -> User:
    user = User(
        email=str(user_data.email).strip().lower(),
        hashed_password=hash_password(user_data.password),
        first_name=user_data.first_name.strip(),
        last_name=user_data.last_name.strip(),
    )

    profile = Profile(
        user=user,
    )

    session.add(user)
    session.add(profile)

    try:
        await session.commit()
        await session.refresh(user)
    except Exception:
        await session.rollback()
        raise

    return user


async def authenticate_user(
    session: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    user = await get_user_by_email(
        session=session,
        email=email,
    )

    # Cuentas creadas con Google no tienen contraseña.
    if user is None or user.hashed_password is None:
        return None

    if not verify_password(
        plain_password=password,
        hashed_password=user.hashed_password,
    ):
        return None

    if not user.is_active:
        return None

    return user


async def get_user_by_google_sub(
    session: AsyncSession,
    google_sub: str,
) -> User | None:
    statement = select(User).where(User.google_sub == google_sub)
    result = await session.execute(statement)

    return result.scalar_one_or_none()


async def get_or_create_google_user(
    session: AsyncSession,
    identity: "GoogleIdentity",
) -> tuple[User, bool]:
    """Busca la cuenta por Google sub, luego por correo; si no existe la crea.

    Devuelve (usuario, es_nuevo). Vincular por correo es seguro porque
    Google ya verificó que la persona controla ese correo.
    """
    user = await get_user_by_google_sub(session=session, google_sub=identity.sub)
    created = False

    if user is None:
        user = await get_user_by_email(session=session, email=identity.email)

        if user is not None:
            user.google_sub = identity.sub
        else:
            user = User(
                email=identity.email,
                hashed_password=None,
                first_name=identity.given_name,
                last_name=identity.family_name,
                google_sub=identity.sub,
            )
            session.add(user)
            # La foto de Google va también en profile_image_base64, que es
            # el campo que leen todas las pantallas (acepta enlaces).
            session.add(
                Profile(
                    user=user,
                    avatar_url=identity.picture,
                    profile_image_base64=identity.picture,
                )
            )
            created = True

    # Google verificó el correo.
    user.is_verified = True

    try:
        await session.commit()
        await session.refresh(user)
    except Exception:
        await session.rollback()
        raise

    return user, created
