from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.rate_limit import rate_limit
from app.api.dependencies import get_current_user
from app.models.user import User
from app.services import media_service
from app.services.media_service import MediaKind, MediaPurpose

router = APIRouter(prefix="/media", tags=["Media"])


class MediaSignRequest(BaseModel):
    purpose: MediaPurpose
    kind: MediaKind


class MediaSignResponse(BaseModel):
    upload_url: str
    api_key: str
    timestamp: str
    signature: str
    folder: str
    allowed_formats: str
    resource_type: str
    max_bytes: int


class MediaStatus(BaseModel):
    enabled: bool


@router.get("/status", response_model=MediaStatus)
async def media_status() -> MediaStatus:
    return MediaStatus(enabled=media_service.is_enabled())


@router.post(
    "/sign",
    response_model=MediaSignResponse,
    summary="Permiso firmado para subir un archivo a Cloudinary",
    dependencies=[Depends(rate_limit("upload", 60, 600))],
)
async def sign_media_upload(
    data: MediaSignRequest,
    current_user: User = Depends(get_current_user),
) -> MediaSignResponse:
    if data.kind not in media_service.allowed_kinds(data.purpose):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Ese tipo de archivo no se permite aquí.",
        )
    if not media_service.is_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Subir archivos aún no está disponible.",
        )

    return MediaSignResponse(
        **media_service.sign_upload(current_user.id, data.purpose, data.kind)
    )
