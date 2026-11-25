import uuid
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.dependencies import get_current_user
from app.db.session import get_db_session
from app.models.cv_file import CvFile
from app.models.user import User
from app.schemas.profile import (
    CvLinkResponse,
    ProfileResponse,
    ProfileUpdate,
    PublicProfileResponse,
)
from app.services.people_service import (
    CV_LINK_SECONDS,
    can_view_cv,
    create_cv_token,
    decode_cv_token,
    get_contact_status,
)
from app.services.profile_service import (
    get_profile_by_user_id,
    update_profile,
)


router = APIRouter(
    prefix="/profiles",
    tags=["Profiles"],
)


@router.get(
    "/me",
    response_model=ProfileResponse,
    summary="Obtener mi perfil profesional",
)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    profile = await get_profile_by_user_id(
        session=session,
        user_id=current_user.id,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario todavía no posee un perfil profesional.",
        )

    return ProfileResponse.model_validate(profile)


@router.patch(
    "/me",
    response_model=ProfileResponse,
    summary="Actualizar mi perfil profesional",
)
async def update_my_profile(
    profile_data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    profile = await get_profile_by_user_id(
        session=session,
        user_id=current_user.id,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario todavía no posee un perfil profesional.",
        )

    updated_profile = await update_profile(
        session=session,
        profile=profile,
        profile_data=profile_data,
    )

    return ProfileResponse.model_validate(updated_profile)


# =====================================================
# CV (archivo real)
# =====================================================
CV_MAX_BYTES = 5 * 1024 * 1024
CV_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


@router.put(
    "/me/cv",
    response_model=ProfileResponse,
    summary="Subir o reemplazar mi CV (PDF o Word, máx. 5 MB)",
)
async def upload_my_cv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProfileResponse:
    file_name = (file.filename or "cv.pdf").strip()[:255]
    extension = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    if extension not in CV_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "El CV debe ser PDF o Word (.doc, .docx).",
        )

    data = await file.read(CV_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "El archivo está vacío.")
    if len(data) > CV_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "El CV no puede pesar más de 5 MB.",
        )

    profile = await get_profile_by_user_id(session=session, user_id=current_user.id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Perfil no encontrado.")

    cv = await session.get(CvFile, current_user.id)
    if cv is None:
        cv = CvFile(user_id=current_user.id)
        session.add(cv)

    cv.file_name = file_name
    cv.mime_type = CV_TYPES[extension]
    cv.size_bytes = len(data)
    cv.data = data
    profile.cv_url = file_name

    try:
        await session.commit()
        await session.refresh(profile)
    except Exception:
        await session.rollback()
        raise

    return ProfileResponse.model_validate(profile)


@router.delete(
    "/me/cv",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quitar mi CV",
)
async def delete_my_cv(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    cv = await session.get(CvFile, current_user.id)
    profile = await get_profile_by_user_id(session=session, user_id=current_user.id)

    if cv is not None:
        await session.delete(cv)
    if profile is not None:
        profile.cv_url = None

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise


@router.get(
    "/cv/{token}",
    summary="Descargar un CV con un enlace temporal",
    response_class=Response,
)
async def download_cv(
    token: str,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    owner_id = decode_cv_token(token)
    cv = await session.get(CvFile, owner_id) if owner_id else None

    if cv is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "El enlace venció o el CV ya no existe.",
        )

    safe_name = quote(cv.file_name)
    return Response(
        content=cv.data,
        media_type=cv.mime_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
            "Cache-Control": "private, no-store",
        },
    )


# =====================================================
# PERFIL DE OTRA PERSONA
# =====================================================
async def _get_user_with_profile(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> User:
    result = await session.execute(
        select(User).options(selectinload(User.profile)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado.")
    return user


@router.get(
    "/{user_id}",
    response_model=PublicProfileResponse,
    summary="Ver el perfil de una persona",
)
async def get_public_profile(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PublicProfileResponse:
    user = await _get_user_with_profile(session, user_id)
    profile = user.profile
    is_me = user.id == current_user.id

    contact_status, request_id = (
        ("none", None)
        if is_me
        else await get_contact_status(session, current_user.id, user.id)
    )
    # Correo y teléfono: solo para ti mismo y tus contactos.
    show_private = is_me or contact_status == "accepted"
    is_private = bool(profile and profile.is_private)

    if is_private and not show_private:
        return PublicProfileResponse(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            profile_image_base64=profile.profile_image_base64 if profile else None,
            avatar_url=profile.avatar_url if profile else None,
            university=profile.university if profile else None,
            is_private=True,
            limited=True,
            contact_status=contact_status,
            contact_request_id=request_id,
        )

    has_cv = (
        await session.execute(select(CvFile.user_id).where(CvFile.user_id == user.id))
    ).first() is not None

    return PublicProfileResponse(
        user_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        profile_image_base64=profile.profile_image_base64 if profile else None,
        avatar_url=profile.avatar_url if profile else None,
        university=profile.university if profile else None,
        academic_level=profile.academic_level if profile else None,
        career=profile.career if profile else None,
        academic_cycle=profile.academic_cycle if profile else None,
        bio=profile.bio if profile else None,
        portfolio_url=profile.portfolio_url if profile else None,
        skills=(profile.skills or []) if profile else [],
        has_cv=has_cv,
        email=user.email if show_private else None,
        phone=(profile.phone if profile else None) if show_private else None,
        is_me=is_me,
        is_private=is_private,
        contact_status=contact_status,
        contact_request_id=request_id,
    )


@router.post(
    "/{user_id}/cv-link",
    response_model=CvLinkResponse,
    summary="Obtener un enlace temporal para ver el CV de una persona",
)
async def create_cv_link(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CvLinkResponse:
    if not await can_view_cv(session, current_user.id, user_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Solo sus contactos y las empresas a las que se postuló pueden ver "
            "este CV.",
        )

    cv = await session.execute(
        select(CvFile.file_name).where(CvFile.user_id == user_id)
    )
    file_name = cv.scalar_one_or_none()
    if file_name is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esta persona no tiene CV.")

    return CvLinkResponse(
        path=f"/profiles/cv/{create_cv_token(user_id)}",
        file_name=file_name,
        expires_in=CV_LINK_SECONDS,
    )
