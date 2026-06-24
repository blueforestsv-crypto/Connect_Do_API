import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.contact_request import ContactRequest
from app.models.notification import Notification
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


def _get_full_name(user: User) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()

    if full_name:
        return full_name

    return user.email


def _get_publication_notification_type(
    publication_data: PublicationCreate,
) -> str:
    possible_type = (
        getattr(publication_data, "type", None)
        or getattr(publication_data, "publication_type", None)
        or getattr(publication_data, "category", None)
        or ""
    )

    possible_type = str(possible_type).lower()

    is_internship = getattr(publication_data, "is_internship", False)

    if is_internship:
        return "opportunity"

    opportunity_keywords = [
        "internship",
        "pasantia",
        "pasantía",
        "opportunity",
        "oportunidad",
        "job",
        "empleo",
        "vacante",
        "oferta",
    ]

    if any(keyword in possible_type for keyword in opportunity_keywords):
        return "opportunity"

    return "publication"


async def _get_accepted_contact_ids(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[uuid.UUID]:
    result = await session.execute(
        select(ContactRequest)
        .where(
            or_(
                ContactRequest.requester_id == user_id,
                ContactRequest.receiver_id == user_id,
            ),
            ContactRequest.status == "accepted",
        )
        .options(
            joinedload(ContactRequest.requester),
            joinedload(ContactRequest.receiver),
        )
    )

    accepted_requests = result.scalars().unique().all()

    contact_ids: list[uuid.UUID] = []

    for request in accepted_requests:
        contact_id = (
            request.receiver_id
            if request.requester_id == user_id
            else request.requester_id
        )

        if contact_id != user_id:
            contact_ids.append(contact_id)

    return contact_ids


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
    publication = await create_publication(
        session=session,
        author_id=current_user.id,
        publication_data=publication_data,
    )

    contact_ids = await _get_accepted_contact_ids(
        session=session,
        user_id=current_user.id,
    )

    notification_type = _get_publication_notification_type(publication_data)
    author_name = _get_full_name(current_user)

    if notification_type == "opportunity":
        title = "Nueva oportunidad"
        message = f"{author_name} publicó una nueva oportunidad."
    else:
        title = "Nueva publicación"
        message = f"{author_name} hizo una nueva publicación."

    for contact_id in contact_ids:
        notification = Notification(
            user_id=contact_id,
            type=notification_type,
            title=title,
            message=message,
            related_user_id=current_user.id,
            related_publication_id=publication.id,
            is_read=False,
        )

        session.add(notification)

    await session.commit()

    return publication


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