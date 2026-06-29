import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ApplicationStatus = Literal[
    "new",
    "reviewed",
    "contacted",
    "interview",
    "selected",
    "rejected",
]


class ApplicationCreate(BaseModel):
    publication_id: uuid.UUID
    cover_message: str | None = Field(default=None, max_length=2000)


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus


class ApplicationPublicationResponse(BaseModel):
    id: uuid.UUID
    title: str
    type: str
    location: str | None
    modality: str | None

    model_config = ConfigDict(from_attributes=True)


class ApplicationStudentResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    profile_image_base64: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ApplicationCompanyResponse(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str

    model_config = ConfigDict(from_attributes=True)


class ApplicationResponse(BaseModel):
    id: uuid.UUID
    publication_id: uuid.UUID
    student_id: uuid.UUID
    company_id: uuid.UUID
    status: str
    profile_snapshot: dict[str, Any] | None
    cv_url: str | None
    cover_message: str | None
    created_at: datetime
    updated_at: datetime

    publication: ApplicationPublicationResponse | None = None
    student: ApplicationStudentResponse | None = None
    company: ApplicationCompanyResponse | None = None

    model_config = ConfigDict(from_attributes=True)