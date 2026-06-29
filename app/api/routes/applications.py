import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.application import Application
from app.models.publication import Publication
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
)

router = APIRouter(prefix="/applications", tags=["Applications"])


def _build_profile_snapshot(user: User) -> dict:
    profile = user.__dict__.get("profile")

    return {
        "user_id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": profile.phone if profile else None,
        "university": profile.university if profile else None,
        "academic_level": profile.academic_level if profile else None,
        "career": profile.career if profile else None,
        "academic_cycle": profile.academic_cycle if profile else None,
        "bio": profile.bio if profile else None,
        "portfolio_url": profile.portfolio_url if profile else None,
        "avatar_url": profile.avatar_url if profile else None,
        "profile_image_base64": profile.profile_image_base64 if profile else None,
        "cv_url": profile.cv_url if profile else None,
    }


async def _get_application_with_relations(
    session: AsyncSession,
    application_id: uuid.UUID,
) -> Application | None:
    result = await session.execute(
        select(Application)
        .options(
            selectinload(Application.publication),
            selectinload(Application.student),
            selectinload(Application.company),
        )
        .where(Application.id == application_id)
    )

    return result.scalar_one_or_none()


@router.post(
    "",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_application_endpoint(
    application_data: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApplicationResponse:
    publication_result = await session.execute(
        select(Publication).where(
            Publication.id == application_data.publication_id,
            Publication.is_active.is_(True),
        )
    )
    publication = publication_result.scalar_one_or_none()

    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    if publication.author_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot apply to your own publication",
        )

    profile_snapshot = _build_profile_snapshot(current_user)

    application = Application(
        publication_id=publication.id,
        student_id=current_user.id,
        company_id=publication.author_id,
        status="new",
        profile_snapshot=profile_snapshot,
        cv_url=profile_snapshot.get("cv_url"),
        cover_message=application_data.cover_message,
    )

    session.add(application)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already applied to this publication",
        )

    created_application = await _get_application_with_relations(
        session=session,
        application_id=application.id,
    )

    if created_application is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Application could not be loaded",
        )

    return created_application


@router.get(
    "/me",
    response_model=list[ApplicationResponse],
)
async def list_my_applications_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApplicationResponse]:
    result = await session.execute(
        select(Application)
        .options(
            selectinload(Application.publication),
            selectinload(Application.student),
            selectinload(Application.company),
        )
        .where(Application.student_id == current_user.id)
        .order_by(Application.created_at.desc())
    )

    return list(result.scalars().all())


@router.get(
    "/received",
    response_model=list[ApplicationResponse],
)
async def list_received_applications_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApplicationResponse]:
    result = await session.execute(
        select(Application)
        .options(
            selectinload(Application.publication),
            selectinload(Application.student),
            selectinload(Application.company),
        )
        .where(Application.company_id == current_user.id)
        .order_by(Application.created_at.desc())
    )

    return list(result.scalars().all())


@router.get(
    "/publication/{publication_id}",
    response_model=list[ApplicationResponse],
)
async def list_publication_applications_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApplicationResponse]:
    publication_result = await session.execute(
        select(Publication).where(Publication.id == publication_id)
    )
    publication = publication_result.scalar_one_or_none()

    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    if publication.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view applications for your own publications",
        )

    result = await session.execute(
        select(Application)
        .options(
            selectinload(Application.publication),
            selectinload(Application.student),
            selectinload(Application.company),
        )
        .where(Application.publication_id == publication_id)
        .order_by(Application.created_at.desc())
    )

    return list(result.scalars().all())


@router.patch(
    "/{application_id}",
    response_model=ApplicationResponse,
)
async def update_application_status_endpoint(
    application_id: uuid.UUID,
    application_data: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ApplicationResponse:
    result = await session.execute(
        select(Application).where(Application.id == application_id)
    )
    application = result.scalar_one_or_none()

    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    if application.company_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update applications received by your company",
        )

    application.status = application_data.status

    await session.commit()

    updated_application = await _get_application_with_relations(
        session=session,
        application_id=application.id,
    )

    if updated_application is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Application could not be loaded",
        )

    return updated_application