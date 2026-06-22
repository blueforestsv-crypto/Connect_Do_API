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


class PublicationCreate(BaseModel):
    type: PublicationType = "general"
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10)
    location: str | None = Field(default=None, max_length=120)
    modality: PublicationModality | None = None
    image_url: str | None = Field(default=None, max_length=500)


class PublicationUpdate(BaseModel):
    type: PublicationType | None = None
    title: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = Field(default=None, min_length=10)
    location: str | None = Field(default=None, max_length=120)
    modality: PublicationModality | None = None
    image_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class PublicationAuthorResponse(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str

    model_config = ConfigDict(from_attributes=True)


class PublicationResponse(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID
    type: str
    title: str
    description: str
    location: str | None
    modality: str | None
    image_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    author: PublicationAuthorResponse

    model_config = ConfigDict(from_attributes=True)