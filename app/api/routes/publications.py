import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.publication import (
    PublicationCreate,
    PublicationResponse,
    PublicationUpdate,
)
from app.services.publication_service import (
    create_publication,
    delete_publication,
    get_publication_by_id,
    list_publications,
    update_publication,
)

router = APIRouter(prefix="/publications", tags=["Publications"])


@router.post(
    "",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_publication_endpoint(
    publication_data: PublicationCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PublicationResponse:
    return await create_publication(
        session=session,
        author_id=current_user.id,
        publication_data=publication_data,
    )


@router.get(
    "",
    response_model=list[PublicationResponse],
)
async def list_publications_endpoint(
    publication_type: str | None = Query(default=None, alias="type"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> list[PublicationResponse]:
    return await list_publications(
        session=session,
        publication_type=publication_type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{publication_id}",
    response_model=PublicationResponse,
)
async def get_publication_endpoint(
    publication_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> PublicationResponse:
    publication = await get_publication_by_id(
        session=session,
        publication_id=publication_id,
    )

    if publication is None or not publication.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    return publication


@router.patch(
    "/{publication_id}",
    response_model=PublicationResponse,
)
async def update_publication_endpoint(
    publication_id: uuid.UUID,
    publication_data: PublicationUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PublicationResponse:
    publication = await get_publication_by_id(
        session=session,
        publication_id=publication_id,
    )

    if publication is None or not publication.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    if publication.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own publications",
        )

    return await update_publication(
        session=session,
        publication=publication,
        publication_data=publication_data,
    )


@router.delete(
    "/{publication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_publication_endpoint(
    publication_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    publication = await get_publication_by_id(
        session=session,
        publication_id=publication_id,
    )

    if publication is None or not publication.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Publication not found",
        )

    if publication.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own publications",
        )

    await delete_publication(
        session=session,
        publication=publication,
    )