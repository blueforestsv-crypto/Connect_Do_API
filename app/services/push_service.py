"""Notificaciones push con Firebase Cloud Messaging (API HTTP v1).

Cada vez que se guarda una fila en `notifications`, se envía también un push
a los teléfonos de esa persona. El envío ocurre DESPUÉS del commit y en
segundo plano: si Firebase falla, la notificación dentro de la app no se
pierde ni se hace más lenta la respuesta.

Se activa con FIREBASE_SERVICE_ACCOUNT_JSON; sin esa variable no hace nada.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
ANDROID_CHANNEL_ID = "connect_do_general"

_PENDING_KEY = "pending_pushes"
_background_tasks: set[asyncio.Task] = set()
_access_token: tuple[str, float] | None = None  # (token, vence_en)


@dataclass(frozen=True)
class PushMessage:
    user_id: uuid.UUID
    title: str
    body: str
    data: dict[str, str]


# =====================================================
# CONFIGURACIÓN
# =====================================================
@lru_cache
def _service_account() -> dict[str, Any] | None:
    raw = settings.firebase_service_account_json.strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
        for key in ("project_id", "client_email", "private_key"):
            if not info.get(key):
                raise ValueError(f"falta {key}")
        return info
    except (ValueError, json.JSONDecodeError) as error:
        logger.error("FIREBASE_SERVICE_ACCOUNT_JSON inválido: %s", error)
        return None


def is_enabled() -> bool:
    return _service_account() is not None


async def _get_access_token(client: httpx.AsyncClient) -> str:
    """Token OAuth de Google (1 h), reutilizado hasta 5 min antes de vencer."""
    global _access_token
    if _access_token and _access_token[1] > time.time() + 300:
        return _access_token[0]

    info = _service_account()
    assert info is not None
    now = int(time.time())
    token_uri = info.get("token_uri", "https://oauth2.googleapis.com/token")
    assertion = jwt.encode(
        {
            "iss": info["client_email"],
            "scope": FCM_SCOPE,
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        },
        info["private_key"],
        algorithm="RS256",
    )
    response = await client.post(
        token_uri,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
    )
    response.raise_for_status()
    payload = response.json()
    _access_token = (
        payload["access_token"],
        time.time() + int(payload.get("expires_in", 3600)),
    )
    return _access_token[0]


# =====================================================
# ENVÍO
# =====================================================
def build_fcm_message(token: str, push: PushMessage) -> dict[str, Any]:
    return {
        "message": {
            "token": token,
            "notification": {"title": push.title, "body": push.body[:240]},
            "data": push.data,
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": ANDROID_CHANNEL_ID,
                    "tag": push.data.get("type", "general"),
                },
            },
        }
    }


def _is_dead_token(response: httpx.Response) -> bool:
    """Firebase indica que el token ya no sirve (app desinstalada, etc.)."""
    if response.status_code == 404:
        return True
    if response.status_code == 400:
        return "UNREGISTERED" in response.text or "registration token" in (
            response.text
        )
    return False


async def send_pushes(pushes: list[PushMessage]) -> None:
    info = _service_account()
    if info is None or not pushes:
        return

    # Import aquí para evitar ciclos (session -> models -> este módulo).
    from app.db.session import AsyncSessionLocal
    from app.models.device_token import DeviceToken

    user_ids = {push.user_id for push in pushes}
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(DeviceToken.user_id, DeviceToken.token).where(
                DeviceToken.user_id.in_(user_ids)
            )
        )
        tokens: dict[uuid.UUID, list[str]] = {}
        for user_id, token in rows.all():
            tokens.setdefault(user_id, []).append(token)

        if not tokens:
            return

        url = (
            f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send"
        )
        dead: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                headers = {"Authorization": f"Bearer {await _get_access_token(client)}"}
                for push in pushes:
                    for token in tokens.get(push.user_id, []):
                        response = await client.post(
                            url,
                            headers=headers,
                            json=build_fcm_message(token, push),
                        )
                        if _is_dead_token(response):
                            dead.append(token)
                        elif response.status_code >= 300:
                            logger.warning(
                                "FCM respondió %s: %s",
                                response.status_code,
                                response.text[:300],
                            )
        except httpx.HTTPError as error:
            logger.warning("No se pudo enviar push: %s", error)

        if dead:
            await session.execute(
                delete(DeviceToken).where(DeviceToken.token.in_(dead))
            )
            await session.commit()


def _schedule(pushes: list[PushMessage]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(send_pushes(pushes))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# =====================================================
# GANCHO: cada notificación nueva -> push
# =====================================================
def push_from_notification(notification: Any) -> PushMessage:
    data = {
        "type": str(notification.type or ""),
        "notification_id": str(notification.id or ""),
    }
    for field in (
        "related_user_id",
        "related_publication_id",
        "related_message_id",
        "related_contact_request_id",
    ):
        value = getattr(notification, field, None)
        if value:
            data[field] = str(value)

    return PushMessage(
        user_id=notification.user_id,
        title=notification.title or "Connect Do",
        body=notification.message or "",
        data=data,
    )


@event.listens_for(Session, "after_flush")
def _collect_new_notifications(session: Session, flush_context: Any) -> None:
    if not is_enabled():
        return
    from app.models.notification import Notification

    pending = session.info.setdefault(_PENDING_KEY, [])
    for obj in session.new:
        if isinstance(obj, Notification):
            pending.append(push_from_notification(obj))


@event.listens_for(Session, "after_commit")
def _send_after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if pending:
        _schedule(list(pending))


@event.listens_for(Session, "after_rollback")
def _discard_on_rollback(session: Session) -> None:
    session.info.pop(_PENDING_KEY, None)
