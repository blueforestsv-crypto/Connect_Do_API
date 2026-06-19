import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from app.schemas.profile import ProfileUpdate


async def get_profile_by_user_id(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Profile | None:
    statement = select(Profile).where(
        Profile.user_id == user_id,
    )

    result = await session.execute(statement)

    return result.scalar_one_or_none()


async def create_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> Profile:
    profile = Profile(
        user_id=user_id,
    )

    session.add(profile)

    try:
        await session.commit()
        await session.refresh(profile)
    except Exception:
        await session.rollback()
        raise

    return profile


async def update_profile(
    session: AsyncSession,
    profile: Profile,
    profile_data: ProfileUpdate,
) -> Profile:
    update_data = profile_data.model_dump(
        exclude_unset=True,
    )

    for field_name, value in update_data.items():
        setattr(profile, field_name, value)

    try:
        await session.commit()
        await session.refresh(profile)
    except Exception:
        await session.rollback()
        raise

    return profile
