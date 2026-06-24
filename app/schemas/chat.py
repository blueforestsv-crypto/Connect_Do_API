import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str

    career: str | None = None
    profile_image_base64: str | None = None

    model_config = ConfigDict(from_attributes=True)


class MessageCreate(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=2000,
    )


class MessageResponse(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    content: str
    is_read: bool
    created_at: datetime

    sender: ChatUserResponse
    receiver: ChatUserResponse

    model_config = ConfigDict(from_attributes=True)


class ConversationResponse(BaseModel):
    contact: ChatUserResponse
    last_message: MessageResponse | None = None
    unread_count: int = 0