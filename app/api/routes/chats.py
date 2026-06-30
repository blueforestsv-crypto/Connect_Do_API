import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.contact_request import ContactRequest
from app.models.message import Message
from app.models.notification import Notification
from app.models.user import User
from app.schemas.chat import (
    ChatUserResponse,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(
    prefix="/chats",
    tags=["Chats"],
)


def _build_chat_user(user: User) -> ChatUserResponse:
    profile = user.__dict__.get("profile")

    return ChatUserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        career=profile.career if profile else None,
        profile_image_base64=profile.profile_image_base64 if profile else None,
    )


def _get_full_name(user: User) -> str:
    full_name = f"{user.first_name} {user.last_name}".strip()

    if full_name:
        return full_name

    return user.email


async def _are_contacts(
    session: AsyncSession,
    user_a_id: uuid.UUID,
    user_b_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        select(ContactRequest.id).where(
            or_(
                and_(
                    ContactRequest.requester_id == user_a_id,
                    ContactRequest.receiver_id == user_b_id,
                ),
                and_(
                    ContactRequest.requester_id == user_b_id,
                    ContactRequest.receiver_id == user_a_id,
                ),
            ),
            ContactRequest.status == "accepted",
        )
    )

    return result.scalar_one_or_none() is not None


async def _has_existing_conversation(
    session: AsyncSession,
    user_a_id: uuid.UUID,
    user_b_id: uuid.UUID,
) -> bool:
    result = await session.execute(
        select(Message.id)
        .where(
            or_(
                and_(
                    Message.sender_id == user_a_id,
                    Message.receiver_id == user_b_id,
                ),
                and_(
                    Message.sender_id == user_b_id,
                    Message.receiver_id == user_a_id,
                ),
            )
        )
        .limit(1)
    )

    return result.scalar_one_or_none() is not None


async def _can_chat(
    session: AsyncSession,
    user_a_id: uuid.UUID,
    user_b_id: uuid.UUID,
) -> bool:
    are_contacts = await _are_contacts(
        session=session,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
    )

    if are_contacts:
        return True

    has_existing_conversation = await _has_existing_conversation(
        session=session,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
    )

    return has_existing_conversation


async def _get_contact_or_404(
    session: AsyncSession,
    contact_id: uuid.UUID,
) -> User:
    result = await session.execute(
        select(User)
        .where(User.id == contact_id)
        .options(joinedload(User.profile))
    )

    contact = result.scalar_one_or_none()

    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contacto no encontrado.",
        )

    return contact


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    summary="Ver mis conversaciones",
)
async def get_conversations(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConversationResponse]:
    conversations_by_contact_id: dict[uuid.UUID, ConversationResponse] = {}

    contacts_result = await session.execute(
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
    )

    accepted_contacts = contacts_result.scalars().unique().all()

    for contact_request in accepted_contacts:
        contact = (
            contact_request.receiver
            if contact_request.requester_id == current_user.id
            else contact_request.requester
        )

        conversations_by_contact_id[contact.id] = ConversationResponse(
            contact=_build_chat_user(contact),
            last_message=None,
            unread_count=0,
        )

    messages_result = await session.execute(
        select(Message)
        .where(
            or_(
                Message.sender_id == current_user.id,
                Message.receiver_id == current_user.id,
            )
        )
        .options(
            joinedload(Message.sender).joinedload(User.profile),
            joinedload(Message.receiver).joinedload(User.profile),
        )
        .order_by(Message.created_at.desc())
    )

    messages = messages_result.scalars().unique().all()

    for message in messages:
        contact = (
            message.receiver
            if message.sender_id == current_user.id
            else message.sender
        )

        if contact.id not in conversations_by_contact_id:
            conversations_by_contact_id[contact.id] = ConversationResponse(
                contact=_build_chat_user(contact),
                last_message=MessageResponse.model_validate(message),
                unread_count=0,
            )
        else:
            existing_conversation = conversations_by_contact_id[contact.id]

            if existing_conversation.last_message is None:
                existing_conversation.last_message = MessageResponse.model_validate(
                    message
                )

    conversations = list(conversations_by_contact_id.values())

    for conversation in conversations:
        unread_count_result = await session.execute(
            select(func.count(Message.id)).where(
                Message.sender_id == conversation.contact.id,
                Message.receiver_id == current_user.id,
                Message.is_read.is_(False),
            )
        )

        conversation.unread_count = unread_count_result.scalar_one() or 0

    conversations.sort(
        key=lambda item: (
            item.last_message.created_at if item.last_message else None
        ),
        reverse=True,
    )

    return conversations


@router.get(
    "/{contact_id}/messages",
    response_model=list[MessageResponse],
    summary="Ver mensajes con un contacto",
)
async def get_messages_with_contact(
    contact_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[MessageResponse]:
    contact = await _get_contact_or_404(
        session=session,
        contact_id=contact_id,
    )

    can_chat = await _can_chat(
        session=session,
        user_a_id=current_user.id,
        user_b_id=contact.id,
    )

    if not can_chat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes ver mensajes con tus contactos o conversaciones iniciadas.",
        )

    result = await session.execute(
        select(Message)
        .where(
            or_(
                and_(
                    Message.sender_id == current_user.id,
                    Message.receiver_id == contact.id,
                ),
                and_(
                    Message.sender_id == contact.id,
                    Message.receiver_id == current_user.id,
                ),
            )
        )
        .options(
            joinedload(Message.sender).joinedload(User.profile),
            joinedload(Message.receiver).joinedload(User.profile),
        )
        .order_by(Message.created_at.asc())
        .limit(limit)
        .offset(offset)
    )

    return [
        MessageResponse.model_validate(message)
        for message in result.scalars().unique().all()
    ]


@router.post(
    "/{contact_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar mensaje a un contacto",
)
async def send_message_to_contact(
    contact_id: uuid.UUID,
    message_data: MessageCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> MessageResponse:
    contact = await _get_contact_or_404(
        session=session,
        contact_id=contact_id,
    )

    can_chat = await _can_chat(
        session=session,
        user_a_id=current_user.id,
        user_b_id=contact.id,
    )

    if not can_chat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes enviar mensajes a tus contactos o conversaciones iniciadas.",
        )

    clean_content = message_data.content.strip()

    if not clean_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El mensaje no puede estar vacío.",
        )

    message = Message(
        sender_id=current_user.id,
        receiver_id=contact.id,
        content=clean_content,
        is_read=False,
    )

    session.add(message)

    await session.flush()

    sender_name = _get_full_name(current_user)

    notification = Notification(
        user_id=contact.id,
        type="message",
        title="Nuevo mensaje",
        message=f"{sender_name} te envió un mensaje.",
        related_user_id=current_user.id,
        related_message_id=message.id,
        is_read=False,
    )

    session.add(notification)

    await session.commit()

    result = await session.execute(
        select(Message)
        .where(Message.id == message.id)
        .options(
            joinedload(Message.sender).joinedload(User.profile),
            joinedload(Message.receiver).joinedload(User.profile),
        )
    )

    created_message = result.scalar_one()

    return MessageResponse.model_validate(created_message)


@router.patch(
    "/{contact_id}/read",
    summary="Marcar mensajes como leídos",
)
async def mark_messages_as_read(
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    contact = await _get_contact_or_404(
        session=session,
        contact_id=contact_id,
    )

    can_chat = await _can_chat(
        session=session,
        user_a_id=current_user.id,
        user_b_id=contact.id,
    )

    if not can_chat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes marcar mensajes de tus contactos o conversaciones iniciadas.",
        )

    result = await session.execute(
        select(Message).where(
            Message.sender_id == contact.id,
            Message.receiver_id == current_user.id,
            Message.is_read.is_(False),
        )
    )

    unread_messages = result.scalars().all()

    for message in unread_messages:
        message.is_read = True

    await session.commit()

    return {
        "updated": len(unread_messages),
    }