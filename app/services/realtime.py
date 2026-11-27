"""Tiempo real por WebSocket: cada teléfono abierto mantiene una conexión
y el servidor le empuja eventos (mensaje nuevo, leído, escribiendo,
reacción, eliminado, en línea).

En memoria: el servidor corre en una sola instancia en Render. Si algún día
hay varias, esto se cambia por Redis pub/sub sin tocar las rutas.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._sockets: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)

    def is_online(self, user_id: uuid.UUID) -> bool:
        return bool(self._sockets.get(user_id))

    async def connect(self, user_id: uuid.UUID, socket: WebSocket) -> bool:
        """Devuelve True si es la primera conexión (pasa a "en línea")."""
        first = not self._sockets.get(user_id)
        self._sockets[user_id].add(socket)
        return first

    def disconnect(self, user_id: uuid.UUID, socket: WebSocket) -> bool:
        """Devuelve True si era la última conexión (pasa a "desconectado")."""
        sockets = self._sockets.get(user_id)
        if not sockets:
            return False
        sockets.discard(socket)
        if not sockets:
            self._sockets.pop(user_id, None)
            return True
        return False

    async def send(self, user_ids, event: dict) -> None:
        """Envía [event] a todas las conexiones de esas personas."""
        targets = [
            (uid, ws)
            for uid in set(user_ids)
            for ws in list(self._sockets.get(uid, ()))
        ]
        if not targets:
            return
        results = await asyncio.gather(
            *(ws.send_json(event) for _, ws in targets), return_exceptions=True
        )
        for (uid, ws), result in zip(targets, results, strict=True):
            if isinstance(result, Exception):
                self.disconnect(uid, ws)


hub = Hub()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
