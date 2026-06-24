import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    message: str

    related_user_id: uuid.UUID | None = None
    related_publication_id: uuid.UUID | None = None
    related_contact_request_id: uuid.UUID | None = None
    related_message_id: uuid.UUID | None = None

    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int