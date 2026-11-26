"""Colección de stickers de cada persona (importados, creados o guardados
desde el chat)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.sticker import Sticker
from app.models.user import User
from app.services import media_service

router = APIRouter(prefix="/stickers", tags=["Stickers"])

MAX_STICKERS = 300


class StickerCreate(BaseModel):
    url: str = Field(max_length=500)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_url(self) -> "StickerCreate":
        if not media_service.is_own_url(self.url):
            raise ValueError("El sticker debe subirse con la app.")
        return self


class StickerResponse(BaseModel):
    id: uuid.UUID
    url: str
    width: int | None = None
    height: int | None = None

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[StickerResponse], summary="Mis stickers")
async def list_stickers(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[Sticker]:
    result = await session.execute(
        select(Sticker)
        .where(Sticker.user_id == current_user.id)
        .order_by(Sticker.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "",
    response_model=StickerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar un sticker a mi colección",
)
async def add_sticker(
    data: StickerCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Sticker:
    count = (
        await session.execute(
            select(func.count())
            .select_from(Sticker)
            .where(Sticker.user_id == current_user.id)
        )
    ).scalar_one()
    if count >= MAX_STICKERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Puedes guardar hasta {MAX_STICKERS} stickers. Borra algunos.",
        )

    # Si ya lo tenía (p. ej. guardó dos veces el mismo), se devuelve ese.
    await session.execute(
        insert(Sticker)
        .values(
            id=uuid.uuid4(),
            user_id=current_user.id,
            url=data.url,
            width=data.width,
            height=data.height,
        )
        .on_conflict_do_nothing(constraint="uq_user_sticker")
    )
    await session.commit()
    result = await session.execute(
        select(Sticker).where(
            Sticker.user_id == current_user.id, Sticker.url == data.url
        )
    )
    return result.scalar_one()


@router.delete("/{sticker_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sticker(
    sticker_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    # El archivo no se borra de Cloudinary: puede estar en mensajes ya
    # enviados o en la colección de otras personas.
    await session.execute(
        delete(Sticker).where(
            Sticker.id == sticker_id, Sticker.user_id == current_user.id
        )
    )
    await session.commit()
