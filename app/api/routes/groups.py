"""Chats grupales."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.schemas.chat import LocationUpdate
from app.api.routes.chats import apply_live_location
from app.api.dependencies import get_current_user
from app.api.routes.chats import message_preview
from app.core.rate_limit import rate_limit
from app.db.session import get_db_session
from app.models.chat_group import ChatGroup, ChatGroupMember, GroupMessage
from app.models.contact_request import ContactRequest
from app.models.user import User
from app.schemas.chat import MessageAttachment, MessageAttachmentResponse, ReactionIn
from app.services import media_service, push_service
from app.services.realtime import hub

router = APIRouter(prefix="/groups", tags=["Groups"])

MAX_MEMBERS = 100


# =====================================================
# ESQUEMAS
# =====================================================
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    member_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_MEMBERS)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    photo_url: str | None = Field(default=None, max_length=500)


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_MEMBERS)


class GroupPerson(BaseModel):
    id: uuid.UUID
    name: str
    profile_image_base64: str | None = None
    role: str | None = None


class GroupReply(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID | None = None
    sender_name: str | None = None
    content: str = ""
    attachment_type: str | None = None
    is_deleted: bool = False


class GroupMessageOut(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    sender: GroupPerson | None = None
    kind: str = "user"
    content: str
    attachment: MessageAttachmentResponse | None = None
    reply_to: GroupReply | None = None
    reactions: dict[str, str] = {}
    is_deleted: bool = False
    created_at: datetime


class GroupMessageIn(BaseModel):
    content: str = Field(default="", max_length=2000)
    attachment: MessageAttachment | None = None
    reply_to_id: uuid.UUID | None = None


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    photo_url: str | None = None
    members: list[GroupPerson] = []
    my_role: str = "member"
    last_message: GroupMessageOut | None = None
    unread_count: int = 0


# =====================================================
# AUXILIARES
# =====================================================
def _person(user: User | None, role: str | None = None) -> GroupPerson | None:
    if user is None:
        return None
    profile = user.__dict__.get("profile")
    return GroupPerson(
        id=user.id,
        name=f"{user.first_name} {user.last_name}".strip() or "Usuario",
        profile_image_base64=profile.profile_image_base64 if profile else None,
        role=role,
    )


def _message_out(message: GroupMessage, replies: dict | None = None) -> GroupMessageOut:
    deleted = message.deleted_at is not None
    reply = None
    original = (replies or {}).get(message.reply_to_id)
    if original is not None:
        gone = original.deleted_at is not None
        reply = GroupReply(
            id=original.id,
            sender_id=original.sender_id,
            sender_name=(
                f"{original.sender.first_name} {original.sender.last_name}".strip()
                if original.__dict__.get("sender")
                else None
            ),
            content="" if gone else (original.content or "")[:160],
            attachment_type=None if gone else original.attachment_type,
            is_deleted=gone,
        )
    return GroupMessageOut(
        id=message.id,
        group_id=message.group_id,
        sender=_person(message.__dict__.get("sender")),
        kind=message.kind,
        content="" if deleted else message.content,
        attachment=(
            MessageAttachmentResponse(
                type=message.attachment_type,
                url=message.attachment_url,
                **(message.attachment_meta or {}),
            )
            if not deleted and message.attachment_type and message.attachment_url
            else None
        ),
        reply_to=reply,
        reactions={} if deleted else (message.reactions or {}),
        is_deleted=deleted,
        created_at=message.created_at,
    )


async def _replies_for(
    session: AsyncSession, messages: list[GroupMessage]
) -> dict[uuid.UUID, GroupMessage]:
    ids = {m.reply_to_id for m in messages if m.reply_to_id}
    if not ids:
        return {}
    rows = await session.execute(
        select(GroupMessage)
        .options(selectinload(GroupMessage.sender))
        .where(GroupMessage.id.in_(ids))
    )
    return {m.id: m for m in rows.scalars().all()}


async def _membership(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> ChatGroupMember:
    member = await session.get(ChatGroupMember, (group_id, user_id))
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No perteneces a este grupo.")
    return member


async def _member_ids(session: AsyncSession, group_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(ChatGroupMember.user_id).where(ChatGroupMember.group_id == group_id)
    )
    return list(rows.scalars().all())


async def _my_contacts(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await session.execute(
        select(ContactRequest.requester_id, ContactRequest.receiver_id).where(
            or_(
                ContactRequest.requester_id == user_id,
                ContactRequest.receiver_id == user_id,
            ),
            ContactRequest.status == "accepted",
        )
    )
    return {b if a == user_id else a for a, b in rows.all()}


async def _group_out(
    session: AsyncSession, group_id: uuid.UUID, viewer_id: uuid.UUID
) -> GroupOut:
    group = (
        await session.execute(
            select(ChatGroup)
            .options(
                selectinload(ChatGroup.members)
                .selectinload(ChatGroupMember.user)
                .selectinload(User.profile)
            )
            .where(ChatGroup.id == group_id)
        )
    ).scalar_one()
    mine = next((m for m in group.members if m.user_id == viewer_id), None)
    return GroupOut(
        id=group.id,
        name=group.name,
        photo_url=group.photo_url,
        members=[
            _person(m.user, m.role)
            for m in sorted(group.members, key=lambda m: m.joined_at)
        ],
        my_role=mine.role if mine else "member",
    )


async def _system(
    session: AsyncSession, group_id: uuid.UUID, text: str
) -> GroupMessage:
    message = GroupMessage(group_id=group_id, content=text, kind="system")
    session.add(message)
    return message


async def _broadcast_message(
    session: AsyncSession, message: GroupMessage, exclude: uuid.UUID | None = None
) -> GroupMessageOut:
    await session.refresh(message, ["sender"])
    out = _message_out(message, await _replies_for(session, [message]))
    members = await _member_ids(session, message.group_id)
    await hub.send(
        members, {"type": "group_message", "message": out.model_dump(mode="json")}
    )
    return out


# =====================================================
# GRUPOS
# =====================================================
@router.post(
    "",
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("group_create", 10, 3600))],
)
async def create_group(
    data: GroupCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> GroupOut:
    contacts = await _my_contacts(session, current_user.id)
    members = [m for m in dict.fromkeys(data.member_ids) if m in contacts]
    if not members:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Agrega al menos a uno de tus contactos."
        )
    group = ChatGroup(name=data.name.strip(), created_by=current_user.id)
    session.add(group)
    await session.flush()
    session.add(
        ChatGroupMember(group_id=group.id, user_id=current_user.id, role="admin")
    )
    for user_id in members:
        session.add(ChatGroupMember(group_id=group.id, user_id=user_id, role="member"))
    name = f"{current_user.first_name} {current_user.last_name}".strip()
    await _system(session, group.id, f"{name} creó el grupo «{group.name}».")
    await session.commit()
    out = await _group_out(session, group.id, current_user.id)
    await hub.send(members, {"type": "group_updated", "group_id": str(group.id)})
    return out


@router.get("", response_model=list[GroupOut], summary="Mis grupos")
async def list_groups(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[GroupOut]:
    memberships = (
        (
            await session.execute(
                select(ChatGroupMember).where(
                    ChatGroupMember.user_id == current_user.id
                )
            )
        )
        .scalars()
        .all()
    )
    result: list[GroupOut] = []
    for member in memberships:
        group = await session.get(ChatGroup, member.group_id)
        if group is None:
            continue
        last = (
            await session.execute(
                select(GroupMessage)
                .options(selectinload(GroupMessage.sender))
                .where(GroupMessage.group_id == group.id)
                .order_by(GroupMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        unread = (
            await session.execute(
                select(func.count())
                .select_from(GroupMessage)
                .where(
                    GroupMessage.group_id == group.id,
                    GroupMessage.kind == "user",
                    or_(
                        GroupMessage.sender_id.is_(None),
                        GroupMessage.sender_id != current_user.id,
                    ),
                    GroupMessage.created_at > (member.last_read_at or member.joined_at),
                )
            )
        ).scalar_one()
        result.append(
            GroupOut(
                id=group.id,
                name=group.name,
                photo_url=group.photo_url,
                my_role=member.role,
                last_message=_message_out(last) if last else None,
                unread_count=unread,
            )
        )
    result.sort(
        key=lambda g: g.last_message.created_at.timestamp() if g.last_message else 0,
        reverse=True,
    )
    return result


@router.get("/unread-count")
async def groups_unread(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    total = (
        await session.execute(
            select(func.count())
            .select_from(GroupMessage)
            .join(
                ChatGroupMember,
                and_(
                    ChatGroupMember.group_id == GroupMessage.group_id,
                    ChatGroupMember.user_id == current_user.id,
                ),
            )
            .where(
                GroupMessage.kind == "user",
                or_(
                    GroupMessage.sender_id.is_(None),
                    GroupMessage.sender_id != current_user.id,
                ),
                GroupMessage.created_at
                > func.coalesce(
                    ChatGroupMember.last_read_at, ChatGroupMember.joined_at
                ),
            )
        )
    ).scalar_one()
    return {"total": int(total)}


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> GroupOut:
    await _membership(session, group_id, current_user.id)
    return await _group_out(session, group_id, current_user.id)


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: uuid.UUID,
    data: GroupUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> GroupOut:
    member = await _membership(session, group_id, current_user.id)
    if member.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los administradores.")
    group = await session.get(ChatGroup, group_id)
    if data.name:
        group.name = data.name.strip()
        await _system(session, group_id, f"El grupo ahora se llama «{group.name}».")
    if data.photo_url is not None:
        if data.photo_url and not media_service.is_own_url(data.photo_url):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sube la foto con la app.")
        group.photo_url = data.photo_url or None
    await session.commit()
    await hub.send(
        await _member_ids(session, group_id),
        {"type": "group_updated", "group_id": str(group_id)},
    )
    return await _group_out(session, group_id, current_user.id)


@router.post("/{group_id}/members", response_model=GroupOut)
async def add_members(
    group_id: uuid.UUID,
    data: MembersIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> GroupOut:
    member = await _membership(session, group_id, current_user.id)
    if member.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los administradores.")
    current = set(await _member_ids(session, group_id))
    contacts = await _my_contacts(session, current_user.id)
    new = [
        u for u in dict.fromkeys(data.user_ids) if u in contacts and u not in current
    ]
    if len(current) + len(new) > MAX_MEMBERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El grupo está lleno.")
    names = []
    for user_id in new:
        session.add(ChatGroupMember(group_id=group_id, user_id=user_id, role="member"))
        user = await session.get(User, user_id)
        names.append(user.first_name if user else "alguien")
    if new:
        await _system(
            session,
            group_id,
            f"{current_user.first_name} agregó a {', '.join(names)}.",
        )
    await session.commit()
    await hub.send(
        list(current | set(new)), {"type": "group_updated", "group_id": str(group_id)}
    )
    return await _group_out(session, group_id, current_user.id)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Salir del grupo (mi propio id) o sacar a alguien (admin)."""
    me = await _membership(session, group_id, current_user.id)
    if user_id != current_user.id and me.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo los administradores.")
    target = await session.get(ChatGroupMember, (group_id, user_id))
    if target is None:
        return
    before = await _member_ids(session, group_id)
    await session.delete(target)
    await session.flush()

    remaining = (
        (
            await session.execute(
                select(ChatGroupMember)
                .where(ChatGroupMember.group_id == group_id)
                .order_by(ChatGroupMember.joined_at)
            )
        )
        .scalars()
        .all()
    )
    if not remaining:
        group = await session.get(ChatGroup, group_id)
        await session.delete(group)
        await session.commit()
        return
    if not any(m.role == "admin" for m in remaining):
        remaining[0].role = "admin"

    user = await session.get(User, user_id)
    who = user.first_name if user else "Alguien"
    await _system(
        session,
        group_id,
        f"{who} salió del grupo."
        if user_id == current_user.id
        else f"{current_user.first_name} sacó a {who}.",
    )
    await session.commit()
    await hub.send(before, {"type": "group_updated", "group_id": str(group_id)})


# =====================================================
# MENSAJES
# =====================================================
@router.get("/{group_id}/messages", response_model=list[GroupMessageOut])
async def group_messages(
    group_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    after: datetime | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[GroupMessageOut]:
    member = await _membership(session, group_id, current_user.id)
    query = (
        select(GroupMessage)
        .options(selectinload(GroupMessage.sender).selectinload(User.profile))
        .where(
            GroupMessage.group_id == group_id,
            # Solo lo de desde que entró.
            GroupMessage.created_at >= member.joined_at,
        )
        .order_by(GroupMessage.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if after is not None:
        query = query.where(GroupMessage.created_at > after)
    messages = list((await session.execute(query)).scalars().all())
    messages.reverse()
    replies = await _replies_for(session, messages)
    return [_message_out(m, replies) for m in messages]


@router.post(
    "/{group_id}/messages",
    response_model=GroupMessageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("group_message", 60, 60))],
)
async def send_group_message(
    group_id: uuid.UUID,
    data: GroupMessageIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> GroupMessageOut:
    await _membership(session, group_id, current_user.id)
    text = data.content.strip()
    if not text and data.attachment is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El mensaje está vacío.")
    reply_to = None
    if data.reply_to_id:
        original = await session.get(GroupMessage, data.reply_to_id)
        if original is not None and original.group_id == group_id:
            reply_to = original.id

    attachment = data.attachment
    message = GroupMessage(
        group_id=group_id,
        sender_id=current_user.id,
        content=text,
        reply_to_id=reply_to,
        attachment_type=attachment.type if attachment else None,
        attachment_url=attachment.url if attachment else None,
        attachment_meta=attachment.meta() if attachment else None,
    )
    session.add(message)

    group = await session.get(ChatGroup, group_id)
    members = await _member_ids(session, group_id)
    sender_name = f"{current_user.first_name} {current_user.last_name}".strip()
    for member_id in members:
        if member_id == current_user.id:
            continue
        push_service.queue_push(
            session,
            push_service.PushMessage(
                user_id=member_id,
                title=group.name,
                body=f"{current_user.first_name}: "
                + message_preview(text, attachment.type if attachment else None),
                data={
                    "type": "group_message",
                    "tag": f"group:{group_id}",
                    "group_id": str(group_id),
                    "group_name": group.name,
                    "sender_name": sender_name,
                },
            ),
        )
    # Escribir cuenta como leído para quien envía.
    me = await session.get(ChatGroupMember, (group_id, current_user.id))
    me.last_read_at = datetime.now(UTC)
    await session.commit()
    return await _broadcast_message(session, message)


@router.post("/{group_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_group_read(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    member = await _membership(session, group_id, current_user.id)
    member.last_read_at = datetime.now(UTC)
    await session.commit()


async def _own_group_message(
    session: AsyncSession, message_id: uuid.UUID, user: User
) -> GroupMessage:
    message = await session.get(GroupMessage, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "El mensaje no existe.")
    await _membership(session, message.group_id, user.id)
    return message


@router.post("/messages/{message_id}/react")
async def react_group_message(
    message_id: uuid.UUID,
    data: ReactionIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, dict[str, str]]:
    message = await _own_group_message(session, message_id, current_user)
    reactions = dict(message.reactions or {})
    emoji = (data.emoji or "").strip()
    if emoji:
        reactions[str(current_user.id)] = emoji
    else:
        reactions.pop(str(current_user.id), None)
    message.reactions = reactions or None
    await session.commit()
    await hub.send(
        await _member_ids(session, message.group_id),
        {
            "type": "reaction",
            "group_id": str(message.group_id),
            "message_id": str(message.id),
            "reactions": reactions,
        },
    )
    return {"reactions": reactions}


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_message(
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    message = await _own_group_message(session, message_id, current_user)
    if message.sender_id != current_user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo puedes eliminar los tuyos."
        )
    url = message.attachment_url
    message.deleted_at = datetime.now(UTC)
    message.content = ""
    message.attachment_type = None
    message.attachment_url = None
    message.attachment_meta = None
    message.reactions = None
    await session.commit()
    await hub.send(
        await _member_ids(session, message.group_id),
        {
            "type": "deleted",
            "group_id": str(message.group_id),
            "message_id": str(message.id),
        },
    )
    if url and "/connect_do/chat/" in url:
        await media_service.destroy([url])


async def _own_group_live_location(
    session: AsyncSession, message_id: uuid.UUID, user: User
) -> GroupMessage:
    message = await _own_group_message(session, message_id, user)
    if message.sender_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo quien la comparte.")
    return message


async def _broadcast_location(session, message: GroupMessage, attachment: dict):
    await hub.send(
        await _member_ids(session, message.group_id),
        {
            "type": "location",
            "group_id": str(message.group_id),
            "message_id": str(message.id),
            "attachment": attachment,
        },
    )


@router.patch(
    "/messages/{message_id}/location",
    dependencies=[Depends(rate_limit("live_location", 40, 60))],
)
async def update_group_live_location(
    message_id: uuid.UUID,
    data: LocationUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    message = await _own_group_live_location(session, message_id, current_user)
    attachment = apply_live_location(message, data.lat, data.lng)
    await session.commit()
    await _broadcast_location(session, message, attachment)
    return attachment


@router.post("/messages/{message_id}/location/stop")
async def stop_group_live_location(
    message_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    message = await _own_group_live_location(session, message_id, current_user)
    attachment = apply_live_location(message, None, None)
    await session.commit()
    await _broadcast_location(session, message, attachment)
    return attachment
