"""Límites anti-spam: cuántas veces se puede usar una acción por minuto.

En memoria (el servidor corre en una sola instancia en Render). Si algún día
hay varias instancias, esto se cambia por Redis sin tocar las rutas.
"""

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_hits: dict[str, deque[float]] = defaultdict(deque)
_bearer = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str:
    # Render pone la IP real del cliente en X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "desconocido"


def _check(key: str, limit: int, window: int) -> None:
    now = time.monotonic()
    hits = _hits[key]
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        wait = int(window - (now - hits[0])) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Vas muy rápido. Inténtalo de nuevo en {wait} segundos.",
            headers={"Retry-After": str(wait)},
        )
    hits.append(now)


def rate_limit(bucket: str, limit: int, per_seconds: int):
    """Dependencia: como mucho [limit] usos cada [per_seconds] segundos, por
    sesión (si hay token) o por IP."""

    async def dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        who = (
            f"t:{credentials.credentials[-24:]}"
            if credentials and credentials.credentials
            else f"ip:{_client_ip(request)}"
        )
        _check(f"{bucket}:{who}", limit, per_seconds)

    return dependency


def reset() -> None:
    """Para pruebas."""
    _hits.clear()
