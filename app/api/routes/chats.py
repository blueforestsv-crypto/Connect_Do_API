import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.rate_limit import rate_limit
from app.services.safety_service import blocked_ids, is_blocked
from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.contact_request import ContactRequest
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services import push_service
from app.schemas.chat import (
    MessageAttachmentResponse,
    ChatUserResponse,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(
    prefix="/chats",
    tags=["Chats"],
)


def _profile_loader(relationship, include_images: bool):
    """
    Carga el perfil del usuario. Si no se piden imágenes, la columna
    profile_image_base64 (muy pesada) no se trae de la base de datos.
    """
    loader = joinedload(relationship).joinedload(User.profile)

    if not include_images:
        loader = loader.defer(Profile.profile_image_base64)

    return loader


def _build_chat_user(user: User, include_images: bool = True) -> ChatUserResponse:
    profile = user.__dict__.get("profile")

    return ChatUserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        career=profile.career if profile else None,
        profile_image_base64=(
            profile.profile_image_base64 if profile and include_images else None
        ),
    )


def _build_message(message: Message, include_images: bool = True) -> MessageResponse:
    # Se construye a mano (sin model_validate) para no tocar la columna
    # diferida de la imagen cuando include_images es False.
    return MessageResponse(
        id=message.id,
        sender_id=message.sender_id,
        receiver_id=message.receiver_id,
        content=message.content,
        attachment=(
            MessageAttachmentResponse(
                type=message.attachment_type,
                url=message.attachment_url,
                **(message.attachment_meta or {}),
            )
            if message.attachment_type and message.attachment_url
            else None
        ),
        is_read=message.is_read,
        created_at=message.created_at,
        sender=_build_chat_user(message.sender, include_images),
        receiver=_build_chat_user(message.receiver, include_images),
    )


_ATTACHMENT_LABELS = {
    "image": "📷 Foto",
    "video": "🎥 Video",
    "audio": "🎤 Nota de voz",
    "sticker": "💟 Sticker",
}


def message_preview(content: str, attachment_type: str | None) -> str:
    """Texto corto para la notificación (y el push) de un mensaje."""
    text = content.strip()
    if text.startswith("[pub:"):
        return "\U0001f4f0 Publicación compartida"
    if attachment_type:
        label = _ATTACHMENT_LABELS.get(attachment_type, "📎 Archivo")
        return f"{label} · {text}" if text else label
    return text[:120] + ("…" if len(text) > 120 else "")


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
    if await is_blocked(session, user_a_id, user_b_id):
        return False

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
        select(User).where(User.id == contact_id).options(joinedload(User.profile))
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
    include_images: bool = True,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConversationResponse]:
    conversations_by_contact_id: dict[uuid.UUID, ConversationResponse] = {}

    # 1. Contactos aceptados (pueden no tener mensajes todavía).
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
            _profile_loader(ContactRequest.requester, include_images),
            _profile_loader(ContactRequest.receiver, include_images),
        )
    )

    for contact_request in contacts_result.scalars().unique().all():
        contact = (
            contact_request.receiver
            if contact_request.requester_id == current_user.id
            else contact_request.requester
        )

        conversations_by_contact_id[contact.id] = ConversationResponse(
            contact=_build_chat_user(contact, include_images),
            last_message=None,
            unread_count=0,
        )

    # 2. Solo el último mensaje de cada conversación (antes se cargaban
    #    TODOS los mensajes del usuario con sus perfiles e imágenes).
    partner_id = case(
        (Message.sender_id == current_user.id, Message.receiver_id),
        else_=Message.sender_id,
    )

    last_message_ids = (
        select(Message.id)
        .where(
            or_(
                Message.sender_id == current_user.id,
                Message.receiver_id == current_user.id,
            )
        )
        .distinct(partner_id)
        .order_by(partner_id, Message.created_at.desc())
    )

    messages_result = await session.execute(
        select(Message)
        .where(Message.id.in_(last_message_ids))
        .options(
            _profile_loader(Message.sender, include_images),
            _profile_loader(Message.receiver, include_images),
        )
    )

    for message in messages_result.scalars().unique().all():
        contact = (
            message.receiver if message.sender_id == current_user.id else message.sender
        )

        last_message = _build_message(message, include_images)

        if contact.id in conversations_by_contact_id:
            conversations_by_contact_id[contact.id].last_message = last_message
        else:
            conversations_by_contact_id[contact.id] = ConversationResponse(
                contact=_build_chat_user(contact, include_images),
                last_message=last_message,
                unread_count=0,
            )

    # 3. No leídos de todas las conversaciones en una sola consulta.
    unread_result = await session.execute(
        select(Message.sender_id, func.count(Message.id))
        .where(
            Message.receiver_id == current_user.id,
            Message.is_read.is_(False),
        )
        .group_by(Message.sender_id)
    )

    for sender_id, unread_count in unread_result.all():
        conversation = conversations_by_contact_id.get(sender_id)

        if conversation is not None:
            conversation.unread_count = unread_count

    blocked = await blocked_ids(session, current_user.id)
    conversations = [
        item
        for contact_id, item in conversations_by_contact_id.items()
        if contact_id not in blocked
    ]

    # Las conversaciones sin mensajes van al final. Antes, mezclar None con
    # fechas en la clave de orden lanzaba TypeError (error 500).
    conversations.sort(
        key=lambda item: (
            item.last_message is not None,
            item.last_message.created_at.timestamp() if item.last_message else 0,
        ),
        reverse=True,
    )

    return conversations


@router.get(
    "/unread-count",
    summary="Total de mensajes sin leer (respuesta mínima, para el contador)",
)
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    result = await session.execute(
        select(func.count())
        .select_from(Message)
        .where(
            Message.receiver_id == current_user.id,
            Message.is_read.is_(False),
        )
    )
    return {"total": int(result.scalar_one())}


@router.get(
    "/{contact_id}/messages",
    response_model=list[MessageResponse],
    summary="Ver mensajes con un contacto",
)
async def get_messages_with_contact(
    contact_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_images: bool = True,
    after: datetime | None = Query(
        default=None,
        description="Solo los mensajes posteriores a esta fecha (para "
        "actualizar el chat sin descargarlo completo).",
    ),
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
        .where(Message.created_at > after if after is not None else true())
        .options(
            _profile_loader(Message.sender, include_images),
            _profile_loader(Message.receiver, include_images),
        )
        # Los más recientes primero para que limit/offset devuelvan los
        # últimos mensajes (antes devolvía los 50 MÁS ANTIGUOS y los nuevos
        # nunca aparecían en conversaciones largas).
        .order_by(Message.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    messages = list(result.scalars().unique().all())
    messages.reverse()  # Se devuelven en orden cronológico.

    return [_build_message(message, include_images) for message in messages]


@router.post(
    "/{contact_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar mensaje a un contacto",
    dependencies=[Depends(rate_limit("message", 60, 60))],
)
async def send_message_to_contact(
    contact_id: uuid.UUID,
    message_data: MessageCreate,
    include_images: bool = True,
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
    attachment = message_data.attachment

    message = Message(
        sender_id=current_user.id,
        receiver_id=contact.id,
        content=clean_content,
        attachment_type=attachment.type if attachment else None,
        attachment_url=attachment.url if attachment else None,
        attachment_meta=attachment.meta() if attachment else None,
        is_read=False,
    )

    session.add(message)

    await session.flush()

    sender_name = _get_full_name(current_user)
    sender_photo = (
        await session.execute(
            select(Profile.profile_image_base64).where(
                Profile.user_id == current_user.id
            )
        )
    ).scalar_one_or_none() or ""

    # Los mensajes NO se guardan en Notificaciones (ya tienen su contador en
    # Chats): solo se manda el push, uno por conversación en la bandeja.
    push_service.queue_push(
        session,
        push_service.PushMessage(
            user_id=contact.id,
            title=sender_name,
            body=message_preview(
                clean_content, attachment.type if attachment else None
            ),
            data={
                "type": "message",
                "tag": f"message:{current_user.id}",
                "related_user_id": str(current_user.id),
                "related_message_id": str(message.id),
                "sender_name": sender_name,
                # Solo enlaces (Cloudinary/Google); nunca base64 en un push.
                "sender_photo": (
                    sender_photo if sender_photo.startswith("https://") else ""
                ),
            },
        ),
    )

    await session.commit()

    result = await session.execute(
        select(Message)
        .where(Message.id == message.id)
        .options(
            _profile_loader(Message.sender, include_images),
            _profile_loader(Message.receiver, include_images),
        )
    )

    created_message = result.unique().scalar_one()

    return _build_message(created_message, include_images)


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
        update(Message)
        .where(
            Message.sender_id == contact.id,
            Message.receiver_id == current_user.id,
            Message.is_read.is_(False),
        )
        .values(is_read=True)
        .execution_options(synchronize_session=False)
    )

    await session.commit()

    return {
        "updated": result.rowcount or 0,
    }
