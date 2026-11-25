"""Fotos, videos y audios en Cloudinary.

La app sube los archivos DIRECTO a Cloudinary (no pasan por Render) con una
firma que genera este servidor. La firma fija la carpeta y los formatos
permitidos, así nadie puede usar tu cuenta para subir otra cosa. En la base
de datos solo se guarda el enlace.

Se activa con CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY y
CLOUDINARY_API_SECRET.
"""

import hashlib
import logging
import re
import time
import uuid
from typing import Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

MediaPurpose = Literal["post", "avatar", "chat", "story"]
MediaKind = Literal["image", "video", "audio"]

_FORMATS: dict[str, str] = {
    "image": "jpg,jpeg,png,webp,heic,heif,gif",
    "video": "mp4,mov,m4v,3gp,webm,mkv",
    "audio": "m4a,aac,mp3,wav,ogg,opus,webm,3gp",
}

# Límites que la app respeta antes de subir (Cloudinary gratis: 10 MB por
# imagen y 100 MB por video).
MAX_BYTES: dict[str, int] = {
    "image": 10 * 1024 * 1024,
    "video": 60 * 1024 * 1024,
    "audio": 10 * 1024 * 1024,
}

# Qué tipos acepta cada uso.
_ALLOWED: dict[str, set[str]] = {
    "post": {"image", "video"},
    "avatar": {"image"},
    "chat": {"image", "video", "audio"},
    "story": {"image", "video"},
}


class MediaNotConfiguredError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    )


def _sign(params: dict[str, str]) -> str:
    """Firma de Cloudinary: sha1 de los parámetros ordenados + el secreto."""
    to_sign = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha1((to_sign + settings.cloudinary_api_secret).encode()).hexdigest()


def allowed_kinds(purpose: str) -> set[str]:
    return _ALLOWED.get(purpose, set())


def sign_upload(user_id: uuid.UUID, purpose: str, kind: str) -> dict:
    if not is_enabled():
        raise MediaNotConfiguredError("Cloudinary no está configurado.")

    # Cloudinary trata el audio como "video".
    resource_type = "image" if kind == "image" else "video"
    params = {
        "folder": f"connect_do/{purpose}/{user_id}",
        "timestamp": str(int(time.time())),
        "allowed_formats": _FORMATS[kind],
    }

    return {
        "upload_url": (
            "https://api.cloudinary.com/v1_1/"
            f"{settings.cloudinary_cloud_name}/{resource_type}/upload"
        ),
        "api_key": settings.cloudinary_api_key,
        "signature": _sign(params),
        "max_bytes": MAX_BYTES[kind],
        "resource_type": resource_type,
        **params,
    }


def is_own_url(url: str | None) -> bool:
    """El enlace es de NUESTRA cuenta de Cloudinary (no de cualquier sitio)."""
    if not url or not settings.cloudinary_cloud_name:
        return False
    prefix = f"https://res.cloudinary.com/{settings.cloudinary_cloud_name}/"
    return url.startswith(prefix)


_PUBLIC_ID = re.compile(r"/upload/(?:[^/]+/)*?(?:v\d+/)?(connect_do/.+?)(?:\.\w+)?$")


def public_id_from_url(url: str) -> str | None:
    match = _PUBLIC_ID.search(url)
    return match.group(1) if match else None


def resource_type_from_url(url: str) -> str:
    return "image" if "/image/upload/" in url else "video"


async def destroy(urls: list[str]) -> None:
    """Borra archivos de Cloudinary (mejor esfuerzo: si falla, solo se avisa
    en el log; el archivo queda huérfano pero nada se rompe)."""
    if not is_enabled():
        return

    async with httpx.AsyncClient(timeout=10) as client:
        for url in urls:
            if not is_own_url(url):
                continue
            public_id = public_id_from_url(url)
            if not public_id:
                continue
            params = {"public_id": public_id, "timestamp": str(int(time.time()))}
            try:
                await client.post(
                    "https://api.cloudinary.com/v1_1/"
                    f"{settings.cloudinary_cloud_name}/"
                    f"{resource_type_from_url(url)}/destroy",
                    data={
                        **params,
                        "api_key": settings.cloudinary_api_key,
                        "signature": _sign(params),
                    },
                )
            except httpx.HTTPError as error:
                logger.warning("No se pudo borrar %s de Cloudinary: %s", url, error)
