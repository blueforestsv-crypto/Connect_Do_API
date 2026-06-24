import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContactUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str

    career: str | None = None
    academic_cycle: str | None = None
    bio: str | None = None
    portfolio_url: str | None = None
    profile_image_base64: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ContactRequestResponse(BaseModel):
    id: uuid.UUID
    requester_id: uuid.UUID
    receiver_id: uuid.UUID
    status: str

    requester: ContactUserResponse
    receiver: ContactUserResponse

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContactUserWithStatusResponse(ContactUserResponse):
    contact_status: str | None = None
    request_id: uuid.UUID | None = None