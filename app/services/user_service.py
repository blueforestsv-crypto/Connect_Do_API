from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreate
from app.services.security import hash_password
from app.services.security import verify_password


async def get_user_by_email(
    session: AsyncSession,
    email: str,
) -> User | None:
    normalized_email = email.strip().lower()

    statement = select(User).where(User.email == normalized_email)
    result = await session.execute(statement)

    return result.scalar_one_or_none()


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

    session.add(user)

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

    if user is None:
        return None

    if not verify_password(
        plain_password=password,
        hashed_password=user.hashed_password,
    ):
        return None

    if not user.is_active:
        return None

    return user
