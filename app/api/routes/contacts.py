import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.contact_request import ContactRequest
from app.models.profile import Profile
from app.models.user import User
from app.schemas.contact import (
    ContactRequestResponse,
    ContactUserResponse,
    ContactUserWithStatusResponse,
)

router = APIRouter(
    prefix="/contacts",
    tags=["Contacts"],
)


def _build_contact_user(
    user: User,
    contact_status: str | None = None,
    request_id: uuid.UUID | None = None,
) -> ContactUserWithStatusResponse:
    profile = user.profile

    return ContactUserWithStatusResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        career=profile.career if profile else None,
        academic_cycle=profile.academic_cycle if profile else None,
        bio=profile.bio if profile else None,
        portfolio_url=profile.portfolio_url if profile else None,
        profile_image_base64=profile.profile_image_base64 if profile else None,
        contact_status=contact_status,
        request_id=request_id,
    )


async def _get_existing_request_between_users(
    session: AsyncSession,
    user_a_id: uuid.UUID,
    user_b_id: uuid.UUID,
) -> ContactRequest | None:
    result = await session.execute(
        select(ContactRequest)
        .where(
            or_(
                and_(
                    ContactRequest.requester_id == user_a_id,
                    ContactRequest.receiver_id == user_b_id,
                ),
                and_(
                    ContactRequest.requester_id == user_b_id,
                    ContactRequest.receiver_id == user_a_id,
                ),
            )
        )
        .options(
            joinedload(ContactRequest.requester).joinedload(User.profile),
            joinedload(ContactRequest.receiver).joinedload(User.profile),
        )
    )

    return result.scalar_one_or_none()


@router.get(
    "/users/search",
    response_model=list[ContactUserWithStatusResponse],
    summary="Buscar usuarios registrados",
)
async def search_users(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ContactUserWithStatusResponse]:
    clean_query = q.strip().lower()

    stmt = (
        select(User)
        .where(User.id != current_user.id)
        .options(joinedload(User.profile))
        .limit(limit)
    )

    if clean_query:
        like_query = f"%{clean_query}%"

        stmt = stmt.where(
            or_(
                User.first_name.ilike(like_query),
                User.last_name.ilike(like_query),
                User.email.ilike(like_query),
            )
        )

    result = await session.execute(stmt)

    users = result.scalars().unique().all()

    response: list[ContactUserWithStatusResponse] = []

    for user in users:
        existing_request = await _get_existing_request_between_users(
            session=session,
            user_a_id=current_user.id,
            user_b_id=user.id,
        )

        contact_status = None
        request_id = None

        if existing_request is not None:
            contact_status = existing_request.status
            request_id = existing_request.id

        response.append(
            _build_contact_user(
                user=user,
                contact_status=contact_status,
                request_id=request_id,
            )
        )

    return response


@router.post(
    "/requests/{receiver_id}",
    response_model=ContactRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar solicitud de contacto",
)
async def send_contact_request(
    receiver_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ContactRequestResponse:
    if receiver_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes enviarte una solicitud a ti mismo.",
        )

    receiver_result = await session.execute(
        select(User)
        .where(User.id == receiver_id)
        .options(joinedload(User.profile))
    )
    receiver = receiver_result.scalar_one_or_none()

    if receiver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario receptor no encontrado.",
        )

    existing_request = await _get_existing_request_between_users(
        session=session,
        user_a_id=current_user.id,
        user_b_id=receiver_id,
    )

    if existing_request is not None:
        if existing_request.status == "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este usuario ya está en tus contactos.",
            )

        if existing_request.status == "pending":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una solicitud pendiente entre estos usuarios.",
            )

        if existing_request.status in ["rejected", "cancelled"]:
            if existing_request.requester_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No puedes reactivar una solicitud creada por otro usuario.",
                )

            existing_request.status = "pending"

            await session.commit()
            await session.refresh(existing_request)

            return ContactRequestResponse.model_validate(existing_request)

    contact_request = ContactRequest(
        requester_id=current_user.id,
        receiver_id=receiver_id,
        status="pending",
    )

    session.add(contact_request)

    await session.commit()

    result = await session.execute(
        select(ContactRequest)
        .where(ContactRequest.id == contact_request.id)
        .options(
            joinedload(ContactRequest.requester).joinedload(User.profile),
            joinedload(ContactRequest.receiver).joinedload(User.profile),
        )
    )

    created_request = result.scalar_one()

    return ContactRequestResponse.model_validate(created_request)


@router.get(
    "/requests/incoming",
    response_model=list[ContactRequestResponse],
    summary="Ver solicitudes recibidas",
)
async def get_incoming_requests(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ContactRequestResponse]:
    result = await session.execute(
        select(ContactRequest)
        .where(
            ContactRequest.receiver_id == current_user.id,
            ContactRequest.status == "pending",
        )
        .options(
            joinedload(ContactRequest.requester).joinedload(User.profile),
            joinedload(ContactRequest.receiver).joinedload(User.profile),
        )
        .order_by(ContactRequest.created_at.desc())
    )

    return [
        ContactRequestResponse.model_validate(request)
        for request in result.scalars().unique().all()
    ]


@router.get(
    "/requests/outgoing",
    response_model=list[ContactRequestResponse],
    summary="Ver solicitudes enviadas",
)
async def get_outgoing_requests(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ContactRequestResponse]:
    result = await session.execute(
        select(ContactRequest)
        .where(
            ContactRequest.requester_id == current_user.id,
            ContactRequest.status == "pending",
        )
        .options(
            joinedload(ContactRequest.requester).joinedload(User.profile),
            joinedload(ContactRequest.receiver).joinedload(User.profile),
        )
        .order_by(ContactRequest.created_at.desc())
    )

    return [
        ContactRequestResponse.model_validate(request)
        for request in result.scalars().unique().all()
    ]


@router.post(
    "/requests/{request_id}/accept",
    response_model=ContactRequestResponse,
    summary="Aceptar solicitud de contacto",
)
async def accept_contact_request(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ContactRequestResponse:
    result = await session.execute(
        select(ContactRequest)
        .where(ContactRequest.id == request_id)
        .options(
            joinedload(ContactRequest.requester).joinedload(User.profile),
            joinedload(ContactRequest.receiver).joinedload(User.profile),
        )
    )

    contact_request = result.scalar_one_or_none()

    if contact_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud no encontrada.",
        )

    if contact_request.receiver_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el receptor puede aceptar esta solicitud.",
        )

    if contact_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta solicitud ya no está pendiente.",
        )

    contact_request.status = "accepted"

    await session.commit()
    await session.refresh(contact_request)

    return ContactRequestResponse.model_validate(contact_request)


@router.post(
    "/requests/{request_id}/reject",
    response_model=ContactRequestResponse,
    summary="Rechazar solicitud de contacto",
)
async def reject_contact_request(
    request_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ContactRequestResponse:
    result = await session.execute(
        select(ContactRequest)
        .where(ContactRequest.id == request_id)
        .options(
            joinedload(ContactRequest.requester).joinedload(User.profile),
            joinedload(ContactRequest.receiver).joinedload(User.profile),
        )
    )

    contact_request = result.scalar_one_or_none()

    if contact_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud no encontrada.",
        )

    if contact_request.receiver_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el receptor puede rechazar esta solicitud.",
        )

    if contact_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta solicitud ya no está pendiente.",
        )

    contact_request.status = "rejected"

    await session.commit()
    await session.refresh(contact_request)

    return ContactRequestResponse.model_validate(contact_request)


@router.get(
    "",
    response_model=list[ContactUserResponse],
    summary="Ver mis contactos",
)
async def get_my_contacts(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ContactUserResponse]:
    result = await session.execute(
        select(ContactRequest)
        .where(
            or_(
                ContactRequest.requester_id == current_user.id,
                ContactRequest.receiver_id == current_user.id,
            ),
            ContactRequest.status == "accepted",
        )
        .options(
            joinedload(ContactRequest.requester).joinedload(User.profile),
            joinedload(ContactRequest.receiver).joinedload(User.profile),
        )
        .order_by(ContactRequest.updated_at.desc())
    )

    accepted_requests = result.scalars().unique().all()

    contacts: list[ContactUserResponse] = []

    for request in accepted_requests:
        contact_user = (
            request.receiver
            if request.requester_id == current_user.id
            else request.requester
        )

        profile = contact_user.profile

        contacts.append(
            ContactUserResponse(
                id=contact_user.id,
                email=contact_user.email,
                first_name=contact_user.first_name,
                last_name=contact_user.last_name,
                career=profile.career if profile else None,
                academic_cycle=profile.academic_cycle if profile else None,
                bio=profile.bio if profile else None,
                portfolio_url=profile.portfolio_url if profile else None,
                profile_image_base64=(
                    profile.profile_image_base64 if profile else None
                ),
            )
        )

    return contacts