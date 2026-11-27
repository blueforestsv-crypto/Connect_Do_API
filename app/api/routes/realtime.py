"""Conexión en tiempo real (WebSocket) y estado "en línea"."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import AsyncSessionLocal, get_db_session
from app.models.chat_group import ChatGroupMember
from app.models.contact_request import ContactRequest
from app.models.user import User
from app.services.realtime import hub, now_iso
from app.services.safety_service import is_blocked
from app.services.security import decode_access_token

router = APIRouter(tags=["Realtime"])


class Presence(BaseModel):
    online: bool
    last_seen_at: datetime | None = None


async def _contact_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(ContactRequest.requester_id, ContactRequest.receiver_id).where(
            or_(
                ContactRequest.requester_id == user_id,
                ContactRequest.receiver_id == user_id,
            ),
            ContactRequest.status == "accepted",
        )
    )
    return [b if a == user_id else a for a, b in rows.all()]


@router.get(
    "/chats/{contact_id}/presence",
    response_model=Presence,
    summary="¿Está en línea? (y su última conexión)",
)
async def presence(
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Presence:
    user = await session.get(User, contact_id)
    if (
        user is None
        or not user.show_presence
        or await is_blocked(session, current_user.id, contact_id)
    ):
        return Presence(online=False)
    return Presence(online=hub.is_online(contact_id), last_seen_at=user.last_seen_at)


@router.websocket("/ws")
async def realtime_socket(socket: WebSocket) -> None:
    """Conectarse con wss://.../ws?token=<access_token>."""
    token = socket.query_params.get("token", "")
    try:
        user_id = uuid.UUID(decode_access_token(token)["sub"])
    except Exception:
        await socket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            await socket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        contacts = await _contact_ids(session, user_id)
        # Si oculta su estado, nadie recibe sus avisos de en línea.
        announce = contacts if user.show_presence else []

    await socket.accept()
    if await hub.connect(user_id, socket):
        await hub.send(
            announce, {"type": "presence", "user_id": str(user_id), "online": True}
        )

    try:
        while True:
            data = await socket.receive_json()
            kind = data.get("type")
            if kind == "ping":
                await socket.send_json({"type": "pong"})
            elif kind == "typing":
                await _forward_typing(user_id, data, contacts)
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        if hub.disconnect(user_id, socket):
            seen = datetime.now(UTC)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(User).where(User.id == user_id).values(last_seen_at=seen)
                )
                await session.commit()
            await hub.send(
                announce,
                {
                    "type": "presence",
                    "user_id": str(user_id),
                    "online": False,
                    "last_seen_at": seen.isoformat(),
                },
            )


async def _forward_typing(
    user_id: uuid.UUID, data: dict, contacts: list[uuid.UUID]
) -> None:
    """ "Escribiendo…": solo a contactos (1 a 1) o a miembros del grupo."""
    is_typing = bool(data.get("is_typing"))
    if data.get("group_id"):
        try:
            group_id = uuid.UUID(str(data["group_id"]))
        except ValueError:
            return
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                select(ChatGroupMember.user_id).where(
                    ChatGroupMember.group_id == group_id
                )
            )
            members = [m for m in rows.scalars().all()]
        if user_id not in members:
            return
        await hub.send(
            [m for m in members if m != user_id],
            {
                "type": "typing",
                "group_id": str(group_id),
                "from": str(user_id),
                "is_typing": is_typing,
                "at": now_iso(),
            },
        )
        return

    try:
        target = uuid.UUID(str(data.get("to")))
    except ValueError:
        return
    if target not in contacts:
        return
    await hub.send(
        [target],
        {
            "type": "typing",
            "from": str(user_id),
            "is_typing": is_typing,
            "at": now_iso(),
        },
    )
