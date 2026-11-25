import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    skills: list[str] | None = Field(default=None, max_length=10)

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for skill in value:
            skill = skill.strip()[:50]
            if skill and skill not in cleaned:
                cleaned.append(skill)
        return cleaned

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
    skills: list[str] | None = None
    is_private: bool

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicProfileResponse(BaseModel):
    """Perfil visto por otra persona. Correo y teléfono solo para contactos."""

    user_id: uuid.UUID
    first_name: str
    last_name: str
    profile_image_base64: str | None = None
    avatar_url: str | None = None

    university: str | None = None
    academic_level: str | None = None
    career: str | None = None
    academic_cycle: str | None = None
    bio: str | None = None
    portfolio_url: str | None = None
    skills: list[str] = []
    has_cv: bool = False

    email: str | None = None
    phone: str | None = None

    is_me: bool = False
    # none | pending_sent | pending_received | accepted
    contact_status: str = "none"
    contact_request_id: uuid.UUID | None = None


class CvLinkResponse(BaseModel):
    # Ruta relativa al servidor; vence en expires_in segundos.
    path: str
    file_name: str
    expires_in: int
