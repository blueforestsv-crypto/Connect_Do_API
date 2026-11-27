import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services import media_service


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
    """Foto o video. Lo nuevo va en Cloudinary (`url`); `base64` queda solo
    para las publicaciones antiguas."""

    type: PublicationMediaType
    url: str | None = Field(default=None, max_length=500)
    thumbnail_url: str | None = Field(default=None, max_length=500)
    base64: str | None = None
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    duration: float | None = Field(default=None, ge=0)
    file_name: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=120)
    size_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_source(self) -> "PublicationMediaItem":
        if not self.url and not self.base64:
            raise ValueError("Cada archivo necesita url o base64.")
        for link in (self.url, self.thumbnail_url):
            if link and not media_service.is_own_url(link):
                raise ValueError("Los archivos deben subirse con la app.")
        return self


class PublicationCreate(BaseModel):
    type: PublicationType = "general"
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10)
    location: str | None = Field(default=None, max_length=120)
    modality: PublicationModality | None = None
    visibility: PublicationVisibility = "contacts"
    image_url: str | None = Field(default=None, max_length=500)
    media_items: list[PublicationMediaItem] = Field(default_factory=list, max_length=6)


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
    # Ya no se envía el correo del autor en el feed (privacidad).
    email: str = ""
    profile_image_base64: str | None = None
    account_type: str = "student"
    company_verified: bool = False

    model_config = ConfigDict(from_attributes=True)

    @field_validator("email", mode="before")
    @classmethod
    def hide_email(cls, value: object) -> str:
        return ""


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

    # Interacciones, calculadas para el usuario que hace la petición.
    likes_count: int = 0
    comments_count: int = 0
    liked_by_me: bool = False
    saved_by_me: bool = False
    is_mine: bool = False

    model_config = ConfigDict(from_attributes=True)


class SaveResponse(BaseModel):
    saved: bool


class LikeResponse(BaseModel):
    liked: bool
    likes_count: int


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("El comentario no puede estar vacío.")
        return value


class CommentAuthorResponse(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    profile_image_base64: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CommentResponse(BaseModel):
    id: uuid.UUID
    publication_id: uuid.UUID
    text: str
    created_at: datetime
    updated_at: datetime
    author: CommentAuthorResponse
    is_mine: bool = False
    # El autor de la publicación también puede borrar comentarios en ella.
    can_delete: bool = False

    model_config = ConfigDict(from_attributes=True)
