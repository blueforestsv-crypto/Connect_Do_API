"""Lo profesional: cuentas de empresa (y su verificación), experiencia y
formación, validar habilidades, visitas al perfil y alertas de empleo."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.api.routes.safety import require_admin
from app.core.rate_limit import rate_limit
from app.db.session import get_db_session
from app.models.notification import Notification
from app.models.professional import (
    JobAlert,
    ProfileEntry,
    ProfileView,
    SkillEndorsement,
)
from app.models.profile import Profile
from app.models.publication import Publication
from app.models.user import User
from app.services.people_service import get_contact_status
from app.services.safety_service import is_blocked

router = APIRouter(tags=["Professional"])

EntryKind = Literal[
    "experience", "education", "certification", "project", "language", "volunteer"
]
JOB_TYPES = ("job", "internship")
OPPORTUNITY_TYPES = ("job", "internship", "social_service", "freelance")
MAX_ENTRIES = 60
MAX_ALERTS = 10


# =====================================================
# ESQUEMAS
# =====================================================
class EntryIn(BaseModel):
    kind: EntryKind
    title: str = Field(min_length=2, max_length=160)
    organization: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, max_length=500)
    position: int = 0

    @model_validator(mode="after")
    def check_dates(self) -> "EntryIn":
        if self.is_current:
            self.end_date = None
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("La fecha de fin no puede ser antes del inicio.")
        return self


class EntryOut(EntryIn):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class AccountTypeUpdate(BaseModel):
    account_type: Literal["student", "company"]
    company_name: str | None = Field(default=None, min_length=2, max_length=160)
    company_sector: str | None = Field(default=None, max_length=120)
    company_size: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def company_needs_name(self) -> "AccountTypeUpdate":
        if self.account_type == "company" and not (self.company_name or "").strip():
            raise ValueError("Escribe el nombre de la empresa.")
        return self


class AccountTypeOut(BaseModel):
    account_type: str
    company_verified: bool
    verification_requested: bool


class EndorseIn(BaseModel):
    skill: str = Field(min_length=1, max_length=50)


class SkillOut(BaseModel):
    name: str
    count: int = 0
    endorsed_by_me: bool = False


class ProfileVisitor(BaseModel):
    user_id: uuid.UUID
    name: str
    headline: str | None = None
    profile_image_base64: str | None = None
    viewed_at: datetime


class ProfileViewsOut(BaseModel):
    total_30_days: int
    visitors: list[ProfileVisitor]


class JobAlertIn(BaseModel):
    query: str | None = Field(default=None, max_length=100)
    type: Literal["job", "internship", "social_service", "freelance"] | None = None
    modality: Literal["remote", "onsite", "hybrid"] | None = None
    location: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def not_empty(self) -> "JobAlertIn":
        if not any([self.query, self.type, self.modality, self.location]):
            raise ValueError("Elige al menos un filtro para la alerta.")
        return self


class JobAlertOut(JobAlertIn):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def not_empty(self) -> "JobAlertOut":  # la salida no se valida
        return self


class AdminCompany(BaseModel):
    user_id: uuid.UUID
    company_name: str
    email: str
    company_sector: str | None
    website: str | None
    requested_at: datetime | None
    verified: bool


class VerifyIn(BaseModel):
    verified: bool


# =====================================================
# CUENTA DE EMPRESA
# =====================================================
async def _profile(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    profile = (
        await session.execute(select(Profile).where(Profile.user_id == user_id))
    ).scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user_id)
        session.add(profile)
    return profile


@router.put(
    "/auth/account-type",
    response_model=AccountTypeOut,
    summary="Cambiar entre cuenta de estudiante y de empresa",
)
async def set_account_type(
    data: AccountTypeUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AccountTypeOut:
    profile = await _profile(session, current_user.id)

    if data.account_type == "company":
        name = (data.company_name or "").strip()
        changed_name = profile.company_name != name
        profile.company_name = name
        profile.company_sector = (data.company_sector or "").strip() or None
        profile.company_size = (data.company_size or "").strip() or None
        # El nombre de la empresa es el que se ve en el feed y el chat.
        current_user.first_name = name
        current_user.last_name = ""
        if current_user.account_type != "company" or changed_name:
            # Un nombre nuevo se vuelve a revisar.
            current_user.company_verified = False
        current_user.account_type = "company"
    else:
        current_user.account_type = "student"
        current_user.company_verified = False
        current_user.company_verification_requested_at = None

    await session.commit()
    return AccountTypeOut(
        account_type=current_user.account_type,
        company_verified=current_user.company_verified,
        verification_requested=current_user.company_verification_requested_at
        is not None,
    )


@router.post(
    "/companies/verification-request",
    response_model=AccountTypeOut,
    summary="Pedir la verificación de la empresa",
)
async def request_verification(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AccountTypeOut:
    if current_user.account_type != "company":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Primero cambia a cuenta de empresa."
        )
    profile = await _profile(session, current_user.id)
    missing = [
        label
        for label, value in (
            ("descripción", profile.bio),
            ("sitio web", profile.portfolio_url),
            ("logo", profile.profile_image_base64),
        )
        if not (value or "").strip()
    ]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Para verificarte, completa en tu perfil: " + ", ".join(missing) + ".",
        )
    current_user.company_verification_requested_at = datetime.now(UTC)
    await session.commit()
    return AccountTypeOut(
        account_type=current_user.account_type,
        company_verified=current_user.company_verified,
        verification_requested=True,
    )


@router.get("/admin/companies", response_model=list[AdminCompany])
async def admin_companies(
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> list[AdminCompany]:
    result = await session.execute(
        select(User)
        .options(selectinload(User.profile))
        .where(
            User.account_type == "company",
            User.company_verification_requested_at.is_not(None),
            User.company_verified.is_(False),
        )
        .order_by(User.company_verification_requested_at)
    )
    return [
        AdminCompany(
            user_id=user.id,
            company_name=(user.profile.company_name if user.profile else None)
            or user.first_name,
            email=user.email,
            company_sector=user.profile.company_sector if user.profile else None,
            website=user.profile.portfolio_url if user.profile else None,
            requested_at=user.company_verification_requested_at,
            verified=user.company_verified,
        )
        for user in result.scalars().all()
    ]


@router.post(
    "/admin/companies/{user_id}/verify", status_code=status.HTTP_204_NO_CONTENT
)
async def admin_verify_company(
    user_id: uuid.UUID,
    data: VerifyIn,
    _: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    user = await session.get(User, user_id)
    if user is None or user.account_type != "company":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Empresa no encontrada.")
    user.company_verified = data.verified
    if not data.verified:
        user.company_verification_requested_at = None
    session.add(
        Notification(
            user_id=user.id,
            type="company_verification",
            title="Verificación de empresa",
            message=(
                "¡Tu empresa fue verificada! Ya aparece con la insignia ✓."
                if data.verified
                else "No pudimos verificar tu empresa. Revisa tus datos y vuelve "
                "a intentarlo."
            ),
            is_read=False,
        )
    )
    await session.commit()


# =====================================================
# EXPERIENCIA, FORMACIÓN…
# =====================================================
async def _entries(session: AsyncSession, user_id: uuid.UUID) -> list[ProfileEntry]:
    result = await session.execute(
        select(ProfileEntry)
        .where(ProfileEntry.user_id == user_id)
        .order_by(
            ProfileEntry.kind,
            ProfileEntry.is_current.desc(),
            ProfileEntry.start_date.desc().nulls_last(),
            ProfileEntry.position,
        )
    )
    return list(result.scalars().all())


@router.get("/profiles/me/entries", response_model=list[EntryOut])
async def my_entries(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ProfileEntry]:
    return await _entries(session, current_user.id)


@router.post(
    "/profiles/me/entries",
    response_model=EntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_entry(
    data: EntryIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileEntry:
    count = (
        await session.execute(
            select(func.count())
            .select_from(ProfileEntry)
            .where(ProfileEntry.user_id == current_user.id)
        )
    ).scalar_one()
    if count >= MAX_ENTRIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Llegaste al máximo.")
    entry = ProfileEntry(user_id=current_user.id, **data.model_dump())
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.put("/profiles/me/entries/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: uuid.UUID,
    data: EntryIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileEntry:
    entry = await session.get(ProfileEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe.")
    for key, value in data.model_dump().items():
        setattr(entry, key, value)
    await session.commit()
    await session.refresh(entry)
    return entry


@router.delete(
    "/profiles/me/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_entry(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.execute(
        delete(ProfileEntry).where(
            ProfileEntry.id == entry_id, ProfileEntry.user_id == current_user.id
        )
    )
    await session.commit()


# =====================================================
# VALIDAR HABILIDADES
# =====================================================
async def skills_with_endorsements(
    session: AsyncSession,
    user_id: uuid.UUID,
    skills: list[str],
    viewer_id: uuid.UUID,
) -> list[SkillOut]:
    if not skills:
        return []
    rows = await session.execute(
        select(SkillEndorsement.skill, SkillEndorsement.endorser_id).where(
            SkillEndorsement.user_id == user_id,
            SkillEndorsement.skill.in_(skills),
        )
    )
    counts: dict[str, int] = {}
    mine: set[str] = set()
    for skill, endorser in rows.all():
        counts[skill] = counts.get(skill, 0) + 1
        if endorser == viewer_id:
            mine.add(skill)
    items = [
        SkillOut(name=s, count=counts.get(s, 0), endorsed_by_me=s in mine)
        for s in skills
    ]
    # Las más validadas primero.
    return sorted(items, key=lambda s: -s.count)


@router.post(
    "/profiles/{user_id}/endorse",
    response_model=list[SkillOut],
    summary="Validar una habilidad de un contacto",
)
async def endorse_skill(
    user_id: uuid.UUID,
    data: EndorseIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[SkillOut]:
    if user_id == current_user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No puedes validarte a ti mismo."
        )
    contact_status, _ = await get_contact_status(session, current_user.id, user_id)
    if contact_status != "accepted":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Solo tus contactos pueden validarte."
        )
    profile = await _profile(session, user_id)
    skills = profile.skills or []
    if data.skill not in skills:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esa habilidad no está.")

    await session.execute(
        insert(SkillEndorsement)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            skill=data.skill,
            endorser_id=current_user.id,
        )
        .on_conflict_do_nothing(constraint="uq_skill_endorsement")
    )
    session.add(
        Notification(
            user_id=user_id,
            type="skill_endorsement",
            title="Validaron tu habilidad",
            message=f"{current_user.first_name} validó tu habilidad «{data.skill}».",
            related_user_id=current_user.id,
            is_read=False,
        )
    )
    await session.commit()
    return await skills_with_endorsements(session, user_id, skills, current_user.id)


@router.delete("/profiles/{user_id}/endorse", response_model=list[SkillOut])
async def remove_endorsement(
    user_id: uuid.UUID,
    data: EndorseIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[SkillOut]:
    await session.execute(
        delete(SkillEndorsement).where(
            SkillEndorsement.user_id == user_id,
            SkillEndorsement.skill == data.skill,
            SkillEndorsement.endorser_id == current_user.id,
        )
    )
    await session.commit()
    profile = await _profile(session, user_id)
    return await skills_with_endorsements(
        session, user_id, profile.skills or [], current_user.id
    )


# =====================================================
# QUIÉN VIO TU PERFIL
# =====================================================
async def record_profile_view(
    session: AsyncSession, viewer_id: uuid.UUID, viewed_id: uuid.UUID
) -> None:
    if viewer_id == viewed_id:
        return
    await session.execute(
        insert(ProfileView)
        .values(
            id=uuid.uuid4(),
            viewer_id=viewer_id,
            viewed_id=viewed_id,
            day=datetime.now(UTC).date(),
        )
        .on_conflict_do_nothing(constraint="uq_profile_view")
    )
    await session.commit()


@router.get("/profiles/me/views", response_model=ProfileViewsOut)
async def my_profile_views(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileViewsOut:
    since = datetime.now(UTC).date() - timedelta(days=30)
    result = await session.execute(
        select(ProfileView, User)
        .join(User, User.id == ProfileView.viewer_id)
        .options(selectinload(User.profile))
        .where(
            ProfileView.viewed_id == current_user.id,
            ProfileView.day >= since,
            User.is_active.is_(True),
        )
        .order_by(ProfileView.viewed_at.desc())
    )
    latest: dict[uuid.UUID, ProfileVisitor] = {}
    total = 0
    for view, user in result.all():
        total += 1
        if user.id in latest or await is_blocked(session, current_user.id, user.id):
            continue
        latest[user.id] = ProfileVisitor(
            user_id=user.id,
            name=f"{user.first_name} {user.last_name}".strip(),
            headline=user.profile.headline if user.profile else None,
            profile_image_base64=(
                user.profile.profile_image_base64 if user.profile else None
            ),
            viewed_at=view.viewed_at,
        )
    return ProfileViewsOut(total_30_days=total, visitors=list(latest.values())[:50])


# =====================================================
# ALERTAS DE EMPLEO
# =====================================================
@router.get("/job-alerts", response_model=list[JobAlertOut])
async def list_alerts(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[JobAlert]:
    result = await session.execute(
        select(JobAlert)
        .where(JobAlert.user_id == current_user.id)
        .order_by(JobAlert.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/job-alerts",
    response_model=JobAlertOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("job_alert", 20, 3600))],
)
async def create_alert(
    data: JobAlertIn,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> JobAlert:
    count = (
        await session.execute(
            select(func.count())
            .select_from(JobAlert)
            .where(JobAlert.user_id == current_user.id)
        )
    ).scalar_one()
    if count >= MAX_ALERTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Puedes tener hasta {MAX_ALERTS} alertas.",
        )
    alert = JobAlert(
        user_id=current_user.id,
        query=(data.query or "").strip() or None,
        type=data.type,
        modality=data.modality,
        location=(data.location or "").strip() or None,
    )
    session.add(alert)
    await session.commit()
    await session.refresh(alert)
    return alert


@router.delete("/job-alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await session.execute(
        delete(JobAlert).where(
            JobAlert.id == alert_id, JobAlert.user_id == current_user.id
        )
    )
    await session.commit()


def alert_matches(alert: JobAlert, publication: Publication) -> bool:
    if alert.type and alert.type != publication.type:
        return False
    if alert.modality and alert.modality != publication.modality:
        return False
    if (
        alert.location
        and alert.location.lower() not in (publication.location or "").lower()
    ):
        return False
    if alert.query:
        text = f"{publication.title} {publication.description}".lower()
        if not all(word in text for word in alert.query.lower().split()):
            return False
    return True


async def notify_job_alerts(
    session: AsyncSession, publication: Publication, author_name: str
) -> int:
    """Avisa a quienes tienen una alerta que coincide (sin guardar commit)."""
    if publication.type not in OPPORTUNITY_TYPES or publication.visibility != "public":
        return 0
    result = await session.execute(
        select(JobAlert).where(JobAlert.user_id != publication.author_id)
    )
    notified: set[uuid.UUID] = set()
    for alert in result.scalars().all():
        if alert.user_id in notified or not alert_matches(alert, publication):
            continue
        if await is_blocked(session, alert.user_id, publication.author_id):
            continue
        notified.add(alert.user_id)
        session.add(
            Notification(
                user_id=alert.user_id,
                type="job_alert",
                title="Nueva oportunidad para ti",
                message=f"{author_name}: {publication.title}",
                related_user_id=publication.author_id,
                related_publication_id=publication.id,
                is_read=False,
            )
        )
    return len(notified)
