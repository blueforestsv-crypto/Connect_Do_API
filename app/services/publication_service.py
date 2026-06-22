import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.publication import Publication
from app.schemas.publication import PublicationCreate, PublicationUpdate


async def create_publication(
    session: AsyncSession,
    author_id: uuid.UUID,
    publication_data: PublicationCreate,
) -> Publication:
    publication = Publication(
        author_id=author_id,
        type=publication_data.type,
        title=publication_data.title,
        description=publication_data.description,
        location=publication_data.location,
        modality=publication_data.modality,
        image_url=publication_data.image_url,
    )

    session.add(publication)
    await session.commit()
    await session.refresh(publication)

    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author))
        .where(Publication.id == publication.id)
    )

    return result.scalar_one()


async def get_publication_by_id(
    session: AsyncSession,
    publication_id: uuid.UUID,
) -> Publication | None:
    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author))
        .where(Publication.id == publication_id)
    )

    return result.scalar_one_or_none()


async def list_publications(
    session: AsyncSession,
    *,
    publication_type: str | None = None,
    only_active: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> list[Publication]:
    query: Select[tuple[Publication]] = (
        select(Publication)
        .options(selectinload(Publication.author))
        .order_by(Publication.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if only_active:
        query = query.where(Publication.is_active.is_(True))

    if publication_type is not None:
        query = query.where(Publication.type == publication_type)

    result = await session.execute(query)

    return list(result.scalars().all())


async def update_publication(
    session: AsyncSession,
    publication: Publication,
    publication_data: PublicationUpdate,
) -> Publication:
    update_data = publication_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(publication, field, value)

    await session.commit()
    await session.refresh(publication)

    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author))
        .where(Publication.id == publication.id)
    )

    return result.scalar_one()


async def delete_publication(
    session: AsyncSession,
    publication: Publication,
) -> None:
    publication.is_active = False
    await session.commit()