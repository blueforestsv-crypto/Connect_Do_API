import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PublicationType = Literal[
    "general",
    "internship",
    "job",
    "social_service",
    "freelance",
    "announcement",
]

PublicationModality = Literal[
    "remote",
    "onsite",
    "hybrid",
]

PublicationVisibility = Literal[
    "public",
    "contacts",
    "private",
]

PublicationMediaType = Literal[
    "image",
    "video",
]


class PublicationMediaItem(BaseModel):
    type: PublicationMediaType
    base64: str = Field(min_length=1)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=120)
    size_bytes: int | None = Field(default=None, ge=0)


class PublicationCreate(BaseModel):
    type: PublicationType = "general"
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10)
    location: str | None = Field(default=None, max_length=120)
    modality: PublicationModality | None = None
    visibility: PublicationVisibility = "contacts"
    image_url: str | None = Field(default=None, max_length=500)
    media_items: list[PublicationMediaItem] = Field(default_factory=list)


class PublicationUpdate(BaseModel):
    type: PublicationType | None = None
    title: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = Field(default=None, min_length=10)
    location: str | None = Field(default=None, max_length=120)
    modality: PublicationModality | None = None
    visibility: PublicationVisibility | None = None
    image_url: str | None = Field(default=None, max_length=500)
    media_items: list[PublicationMediaItem] | None = None
    is_active: bool | None = None


class PublicationAuthorResponse(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str
    profile_image_base64: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PublicationResponse(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    type: str
    title: str
    description: str
    location: str | None
    modality: str | None
    visibility: str
    image_url: str | None
    media_items: list[PublicationMediaItem] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    author: PublicationAuthorResponse

    model_config = ConfigDict(from_attributes=True)