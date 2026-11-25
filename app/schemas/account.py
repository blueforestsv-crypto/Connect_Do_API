from pydantic import BaseModel, EmailStr, Field

CODE_PATTERN = r"^\d{4,8}$"


class MessageResponse(BaseModel):
    message: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    code: str = Field(pattern=CODE_PATTERN)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordChangeRequest(BaseModel):
    # Opcional solo para cuentas creadas con Google que aún no tienen
    # contraseña; si la cuenta tiene una, es obligatoria.
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class EmailChangeRequest(BaseModel):
    new_email: EmailStr
    # Confirmación de identidad si la cuenta tiene contraseña.
    password: str | None = Field(default=None, max_length=128)


class EmailChangeConfirm(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
