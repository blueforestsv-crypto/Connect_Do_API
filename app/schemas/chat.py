import uuid
from datetime import datetime

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


class MessageAttachment(BaseModel):
    type: Literal["image", "video", "audio", "sticker"]
    url: str = Field(max_length=500)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    duration: float | None = Field(default=None, ge=0)
    size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_url(self) -> "MessageAttachment":
        if not media_service.is_own_url(self.url):
            raise ValueError("El archivo debe subirse con la app.")
        return self

    def meta(self) -> dict:
        return self.model_dump(
            include={"width", "height", "duration", "size_bytes"},
            exclude_none=True,
        )


class MessageCreate(BaseModel):
    """Texto, adjunto (foto, video o nota de voz) o ambos."""

    content: str = Field(default="", max_length=2000)
    attachment: MessageAttachment | None = None

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


class MessageResponse(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    content: str
    attachment: MessageAttachmentResponse | None = None
    is_read: bool
    created_at: datetime

    sender: ChatUserResponse
    receiver: ChatUserResponse

    model_config = ConfigDict(from_attributes=True)


class ConversationResponse(BaseModel):
    contact: ChatUserResponse
    last_message: MessageResponse | None = None
    unread_count: int = 0
