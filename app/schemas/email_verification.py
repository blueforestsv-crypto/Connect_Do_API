from pydantic import BaseModel, EmailStr, Field


class EmailVerificationRequest(BaseModel):
    email: EmailStr


class EmailVerificationConfirm(BaseModel):
    token: str = Field(
        min_length=32,
        max_length=500,
    )


class EmailVerificationResponse(BaseModel):
    message: str
    debug_token: str | None = None
