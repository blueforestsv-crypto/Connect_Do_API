from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services.profile_service import (
    get_profile_by_user_id,
    update_profile,
)


router = APIRouter(
    prefix="/profiles",
    tags=["Profiles"],
)


@router.get(
    "/me",
    response_model=ProfileResponse,
    summary="Obtener mi perfil profesional",
)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    profile = await get_profile_by_user_id(
        session=session,
        user_id=current_user.id,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario todavía no posee un perfil profesional.",
        )

    return ProfileResponse.model_validate(profile)


@router.patch(
    "/me",
    response_model=ProfileResponse,
    summary="Actualizar mi perfil profesional",
)
async def update_my_profile(
    profile_data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    profile = await get_profile_by_user_id(
        session=session,
        user_id=current_user.id,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario todavía no posee un perfil profesional.",
        )

    updated_profile = await update_profile(
        session=session,
        profile=profile,
        profile_data=profile_data,
    )

    return ProfileResponse.model_validate(updated_profile)
