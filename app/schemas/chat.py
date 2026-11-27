import uuid
from datetime import datetime, timedelta, UTC

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services import media_service


class ChatUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str

    career: str | None = None
    profile_image_base64: str | None = None

    model_config = ConfigDict(from_attributes=True)


LIVE_LOCATION_MAX_MINUTES = 8 * 60


def maps_url(lat: float, lng: float) -> str:
    return f"https://www.google.com/maps?q={lat:.6f},{lng:.6f}"


class MessageAttachment(BaseModel):
    type: Literal["image", "video", "audio", "sticker", "file", "location"]
    # La ubicación no sube archivo: el enlace lo arma el servidor.
    url: str = Field(default="", max_length=500)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    duration: float | None = Field(default=None, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)
    # Documento: nombre original del archivo.
    name: str | None = Field(default=None, max_length=120)
    # Ubicación.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    # Ubicación en tiempo real: por cuántos minutos se comparte.
    live_minutes: int | None = Field(default=None, ge=1, le=LIVE_LOCATION_MAX_MINUTES)

    @model_validator(mode="after")
    def check_url(self) -> "MessageAttachment":
        if self.type == "location":
            if self.lat is None or self.lng is None:
                raise ValueError("Falta la ubicación.")
            self.url = maps_url(self.lat, self.lng)
            return self
        if not media_service.is_own_url(self.url):
            raise ValueError("El archivo debe subirse con la app.")
        if self.type == "file" and not media_service.is_allowed_file(self.url):
            raise ValueError("Ese tipo de documento no se permite.")
        return self

    def meta(self) -> dict:
        data = self.model_dump(
            include={"width", "height", "duration", "size_bytes", "name", "lat", "lng"},
            exclude_none=True,
        )
        if self.type == "location" and self.live_minutes:
            data["live_until"] = (
                datetime.now(UTC) + timedelta(minutes=self.live_minutes)
            ).isoformat()
        return data


class MessageCreate(BaseModel):
    """Texto, adjunto (foto, video o nota de voz) o ambos."""

    content: str = Field(default="", max_length=2000)
    attachment: MessageAttachment | None = None
    # Responder citando un mensaje.
    reply_to_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def not_empty(self) -> "MessageCreate":
        if not self.content.strip() and self.attachment is None:
            raise ValueError("El mensaje no puede estar vacío.")
        return self


class MessageAttachmentResponse(BaseModel):
    type: str
    url: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    size_bytes: int | None = None
    name: str | None = None
    lat: float | None = None
    lng: float | None = None
    # Ubicación en tiempo real: hasta cuándo se actualiza.
    live_until: datetime | None = None
    updated_at: datetime | None = None


class LocationUpdate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class ReplyPreview(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID | None = None
    content: str = ""
    attachment_type: str | None = None
    is_deleted: bool = False


class MessageResponse(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    content: str
    attachment: MessageAttachmentResponse | None = None
    is_read: bool
    created_at: datetime
    reply_to: ReplyPreview | None = None
    # {user_id: emoji}
    reactions: dict[str, str] = {}
    is_deleted: bool = False

    sender: ChatUserResponse
    receiver: ChatUserResponse

    model_config = ConfigDict(from_attributes=True)


class ReactionIn(BaseModel):
    # None o "" quita mi reacción.
    emoji: str | None = Field(default=None, max_length=16)


class ConversationResponse(BaseModel):
    contact: ChatUserResponse
    last_message: MessageResponse | None = None
    unread_count: int = 0
