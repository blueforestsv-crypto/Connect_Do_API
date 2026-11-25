from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.device_token import DeviceToken
from app.models.user import User
from app.services import push_service

router = APIRouter(prefix="/devices", tags=["Devices"])


class DeviceRegister(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    platform: str = Field(default="android", pattern="^(android|ios|web)$")


class DeviceUnregister(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class DeviceStatus(BaseModel):
    push_enabled: bool


@router.post("", response_model=DeviceStatus, summary="Registrar este teléfono")
async def register_device(
    data: DeviceRegister,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> DeviceStatus:
    # Si el token ya era de otra cuenta (cambió de sesión en el mismo
    # teléfono), pasa a la cuenta actual.
    await session.execute(
        insert(DeviceToken)
        .values(token=data.token, user_id=current_user.id, platform=data.platform)
        .on_conflict_do_update(
            index_elements=[DeviceToken.token],
            set_={
                "user_id": current_user.id,
                "platform": data.platform,
                "updated_at": func.now(),
            },
        )
    )
    await session.commit()
    return DeviceStatus(push_enabled=push_service.is_enabled())


@router.post(
    "/unregister",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dejar de recibir push en este teléfono (al cerrar sesión)",
)
async def unregister_device(
    data: DeviceUnregister,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.execute(
        delete(DeviceToken).where(
            DeviceToken.token == data.token,
            DeviceToken.user_id == current_user.id,
        )
    )
    await session.commit()
