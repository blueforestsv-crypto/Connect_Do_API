from pydantic import BaseModel, EmailStr, Field


class EmailVerificationRequest(BaseModel):
    email: EmailStr


class EmailVerificationConfirm(BaseModel):
    code: str = Field(
        pattern=r"^\d{4,8}$",
        description="Código numérico enviado al correo.",
    )


class EmailVerificationResponse(BaseModel):
    message: str
    # Solo en development: el código, para probar sin proveedor de correo.
    debug_code: str | None = None
