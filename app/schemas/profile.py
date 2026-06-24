import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdate(BaseModel):
    phone: str | None = Field(
        default=None,
        max_length=30,
    )
    university: str | None = Field(
        default=None,
        max_length=200,
    )
    academic_level: str | None = Field(
        default=None,
        max_length=100,
    )
    career: str | None = Field(
        default=None,
        max_length=200,
    )
    academic_cycle: str | None = Field(
        default=None,
        max_length=100,
    )
    bio: str | None = Field(
        default=None,
        max_length=2000,
    )
    portfolio_url: str | None = Field(
        default=None,
        max_length=500,
    )
    avatar_url: str | None = Field(
        default=None,
        max_length=500,
    )
    profile_image_base64: str | None = None
    cv_url: str | None = Field(
        default=None,
        max_length=500,
    )
    is_private: bool | None = None


class ProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID

    phone: str | None
    university: str | None
    academic_level: str | None
    career: str | None
    academic_cycle: str | None
    bio: str | None
    portfolio_url: str | None
    avatar_url: str | None
    profile_image_base64: str | None
    cv_url: str | None
    is_private: bool

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
