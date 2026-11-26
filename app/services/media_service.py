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
    # Android graba AAC dentro de un contenedor MPEG-4: Cloudinary lo
    # identifica como "mp4" aunque el archivo se llame .m4a.
    "audio": "mp4,m4a,aac,mp3,wav,ogg,oga,opus,webm,3gp,amr,flac,caf",
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


# =====================================================
# FOTOS DE PERFIL ANTIGUAS (base64 -> Cloudinary)
# =====================================================
async def upload_base64_image(data: str, folder: str) -> str | None:
    """Sube una imagen en base64 desde el servidor. Devuelve el enlace."""
    if not is_enabled():
        return None
    clean = data.split(",", 1)[1] if data.startswith("data:") else data
    params = {"folder": folder, "timestamp": str(int(time.time()))}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.cloudinary.com/v1_1/"
            f"{settings.cloudinary_cloud_name}/image/upload",
            data={
                **params,
                "api_key": settings.cloudinary_api_key,
                "signature": _sign(params),
                "file": f"data:image/jpeg;base64,{clean.strip()}",
            },
        )
    if response.status_code != 200:
        logger.warning("No se pudo migrar una foto: %s", response.text[:200])
        return None
    return response.json().get("secure_url")


async def fill_missing_photos_from_google() -> int:
    """Cuentas creadas con Google: su foto quedó solo en avatar_url y las
    pantallas leen profile_image_base64. Se copia el enlace (unos bytes)."""
    from sqlalchemy import or_, update

    from app.db.session import AsyncSessionLocal
    from app.models.profile import Profile

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Profile)
            .where(
                or_(
                    Profile.profile_image_base64.is_(None),
                    Profile.profile_image_base64 == "",
                ),
                Profile.avatar_url.startswith("https://"),
            )
            .values(profile_image_base64=Profile.avatar_url)
        )
        await session.commit()
    if result.rowcount:
        logger.info("Fotos de Google copiadas al perfil: %s", result.rowcount)
    return result.rowcount or 0


async def migrate_legacy_avatars(limit: int = 200) -> int:
    """Pasa a Cloudinary las fotos de perfil que siguen en base64, para que
    no viajen completas en cada respuesta. Se ejecuta al arrancar; es seguro
    repetirlo (solo toca las que aún no son enlaces)."""
    await fill_missing_photos_from_google()
    if not is_enabled():
        return 0

    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.profile import Profile

    migrated = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Profile)
            .where(
                Profile.profile_image_base64.is_not(None),
                Profile.profile_image_base64 != "",
                ~Profile.profile_image_base64.startswith("http"),
            )
            .limit(limit)
        )
        for profile in result.scalars().all():
            try:
                url = await upload_base64_image(
                    profile.profile_image_base64,
                    f"connect_do/avatar/{profile.user_id}",
                )
            except httpx.HTTPError:
                url = None
            if url:
                profile.profile_image_base64 = url
                profile.avatar_url = url
                migrated += 1
                await session.commit()
    if migrated:
        logger.info("Fotos de perfil migradas a Cloudinary: %s", migrated)
    return migrated
