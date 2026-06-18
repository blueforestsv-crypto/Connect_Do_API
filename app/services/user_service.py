from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserCreate
from app.services.security import hash_password


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
