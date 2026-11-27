import uuid

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.social import Follow
from app.services.safety_service import blocked_ids_query, is_blocked
from app.models.contact_request import ContactRequest
from app.models.profile import Profile
from app.models.publication import Publication
from app.models.publication_interaction import PublicationSave
from app.models.user import User
from app.schemas.publication import PublicationCreate, PublicationUpdate


async def get_accepted_contact_ids(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[uuid.UUID]:
    result = await session.execute(
        select(ContactRequest).where(
            or_(
                ContactRequest.requester_id == user_id,
                ContactRequest.receiver_id == user_id,
            ),
            ContactRequest.status == "accepted",
        )
    )

    accepted_requests = result.scalars().all()

    contact_ids: list[uuid.UUID] = []

    for request in accepted_requests:
        contact_id = (
            request.receiver_id
            if request.requester_id == user_id
            else request.requester_id
        )

        if contact_id != user_id:
            contact_ids.append(contact_id)

    return contact_ids


async def create_publication(
    session: AsyncSession,
    author_id: uuid.UUID,
    publication_data: PublicationCreate,
    commit: bool = True,
    mentions: list[dict] | None = None,
) -> Publication:
    publication = Publication(
        author_id=author_id,
        type=publication_data.type,
        title=publication_data.title,
        description=publication_data.description,
        location=publication_data.location,
        modality=publication_data.modality,
        visibility=publication_data.visibility,
        image_url=publication_data.image_url,
        media_items=[
            media_item.model_dump() for media_item in publication_data.media_items
        ],
        mentions=mentions or None,
    )

    session.add(publication)

    if not commit:
        await session.flush()
        return publication

    await session.commit()
    await session.refresh(publication)

    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author).selectinload(User.profile))
        .where(Publication.id == publication.id)
    )

    return result.scalar_one()


async def get_publication_by_id(
    session: AsyncSession,
    publication_id: uuid.UUID,
) -> Publication | None:
    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author).selectinload(User.profile))
        .where(Publication.id == publication_id)
    )

    return result.scalar_one_or_none()


def _private_author_ids():
    """Subconsulta: usuarios con perfil privado."""
    return select(Profile.user_id).where(Profile.is_private.is_(True))


async def is_private_profile(session: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(Profile.is_private).where(Profile.user_id == user_id)
    )
    return bool(result.scalar_one_or_none())


async def can_user_view_publication(
    session: AsyncSession,
    publication: Publication,
    user_id: uuid.UUID,
) -> bool:
    if not publication.is_active:
        return False

    if publication.author_id == user_id:
        return True

    if await is_blocked(session, user_id, publication.author_id):
        return False

    if publication.visibility == "private":
        return False

    # Un perfil privado comparte lo "público" solo con sus contactos.
    if publication.visibility == "public" and not await is_private_profile(
        session, publication.author_id
    ):
        return True

    if publication.visibility in ("public", "contacts"):
        result = await session.execute(
            select(ContactRequest.id).where(
                or_(
                    and_(
                        ContactRequest.requester_id == publication.author_id,
                        ContactRequest.receiver_id == user_id,
                    ),
                    and_(
                        ContactRequest.requester_id == user_id,
                        ContactRequest.receiver_id == publication.author_id,
                    ),
                ),
                ContactRequest.status == "accepted",
            )
        )

        return result.scalar_one_or_none() is not None

    return False


async def list_publications(
    session: AsyncSession,
    *,
    current_user_id: uuid.UUID,
    publication_type: str | None = None,
    only_active: bool = True,
    only_mine: bool = False,
    only_saved: bool = False,
    following_only: bool = False,
    author_id: uuid.UUID | None = None,
    search: str | None = None,
    modality: str | None = None,
    location: str | None = None,
    opportunities_only: bool = False,
    verified_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> list[Publication]:
    contact_ids = await get_accepted_contact_ids(
        session=session,
        user_id=current_user_id,
    )

    visible_author_ids = contact_ids + [current_user_id]

    query: Select[tuple[Publication]] = (
        select(Publication)
        .options(selectinload(Publication.author).selectinload(User.profile))
        .where(
            or_(
                and_(
                    Publication.visibility == "public",
                    Publication.author_id.not_in(_private_author_ids()),
                ),
                Publication.author_id == current_user_id,
                and_(
                    Publication.visibility.in_(("public", "contacts")),
                    Publication.author_id.in_(visible_author_ids),
                ),
            )
        )
        .order_by(Publication.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if only_active:
        query = query.where(Publication.is_active.is_(True))

    # Ni bloqueados (en ambos sentidos) ni cuentas suspendidas.
    query = query.where(
        Publication.author_id.not_in(blocked_ids_query(current_user_id)),
        Publication.author_id.not_in(select(User.id).where(User.is_active.is_(False))),
    )

    if publication_type is not None:
        query = query.where(Publication.type == publication_type)

    # Perfil del usuario: solo sus publicaciones (de cualquier visibilidad).
    if only_mine:
        query = query.where(Publication.author_id == current_user_id)

    if author_id is not None:
        query = query.where(Publication.author_id == author_id)

    if following_only:
        query = query.where(
            Publication.author_id.in_(
                select(Follow.followed_id).where(Follow.follower_id == current_user_id)
            )
        )

    if opportunities_only:
        query = query.where(
            Publication.type.in_(("job", "internship", "social_service", "freelance"))
        )
    if modality:
        query = query.where(Publication.modality == modality)
    if location and location.strip():
        query = query.where(Publication.location.ilike(f"%{location.strip()}%"))
    if verified_only:
        query = query.where(
            Publication.author_id.in_(
                select(User.id).where(User.company_verified.is_(True))
            )
        )

    if only_saved:
        query = query.where(
            Publication.id.in_(
                select(PublicationSave.publication_id).where(
                    PublicationSave.user_id == current_user_id
                )
            )
        )

    clean_search = (search or "").strip()
    if clean_search:
        pattern = f"%{clean_search}%"
        query = query.where(
            or_(
                Publication.title.ilike(pattern),
                Publication.description.ilike(pattern),
                Publication.location.ilike(pattern),
                Publication.author_id.in_(
                    select(User.id).where(
                        or_(
                            User.first_name.ilike(pattern),
                            User.last_name.ilike(pattern),
                        )
                    )
                ),
            )
        )

    result = await session.execute(query)

    return list(result.scalars().all())


async def update_publication(
    session: AsyncSession,
    publication: Publication,
    publication_data: PublicationUpdate,
) -> Publication:
    update_data = publication_data.model_dump(exclude_unset=True)

    if "media_items" in update_data and update_data["media_items"] is not None:
        update_data["media_items"] = [
            media_item.model_dump() for media_item in publication_data.media_items or []
        ]

    for field, value in update_data.items():
        setattr(publication, field, value)

    await session.commit()
    await session.refresh(publication)

    result = await session.execute(
        select(Publication)
        .options(selectinload(Publication.author).selectinload(User.profile))
        .where(Publication.id == publication.id)
    )

    return result.scalar_one()


async def delete_publication(
    session: AsyncSession,
    publication: Publication,
) -> None:
    publication.is_active = False
    await session.commit()
