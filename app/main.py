import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import (
    account_router,
    devices_router,
    legal_router,
    media_router,
    stories_router,
    stickers_router,
    safety_router,
    auth_router,
    profiles_router,
    publications_router,
    contacts_router,
    chats_router,
    applications_router,
)
from app.core.config import settings
from app.services import media_service
from app.db.session import get_db_session
from app.api.routes import notifications_router


_startup_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # En segundo plano (solo en producción, nunca en pruebas): arregla fotos
    # de perfil (Google sin copiar, base64 antiguas a Cloudinary).
    if settings.app_env == "production":
        task = asyncio.create_task(_migrate_avatars_safely())
        _startup_tasks.add(task)
        task.add_done_callback(_startup_tasks.discard)
    yield


async def _migrate_avatars_safely() -> None:
    try:
        await _delete_message_notifications()
        await media_service.migrate_legacy_avatars()
    except Exception:  # noqa: BLE001 - nunca debe tumbar el servidor
        logging.getLogger(__name__).exception("Falló el mantenimiento inicial")


async def _delete_message_notifications() -> None:
    """Los mensajes del chat ya no se guardan en Notificaciones; se borran
    los que se acumularon antes."""
    from sqlalchemy import delete

    from app.db.session import AsyncSessionLocal
    from app.models.notification import Notification

    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(Notification).where(Notification.type == "message")
        )
        await session.commit()


app = FastAPI(
    title=settings.app_name,
    description="Backend oficial de la aplicación móvil Connect Do.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configurable con la variable CORS_ORIGINS (por defecto "*", abierto,
# para pruebas locales con Flutter Web que usa puertos aleatorios).
# En producción conviene listar solo los dominios del panel.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Comprime las respuestas de más de 1 KB (el JSON baja 70–90 %).
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(devices_router)
app.include_router(media_router)
app.include_router(stories_router)
app.include_router(stickers_router)
app.include_router(safety_router)
app.include_router(legal_router)
app.include_router(profiles_router)
app.include_router(publications_router)
app.include_router(contacts_router)
app.include_router(chats_router)
app.include_router(notifications_router)
app.include_router(applications_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "connect-do-api",
        "version": "0.1.0",
        "environment": settings.app_env,
    }


@app.get("/health/database", tags=["Health"])
async def database_health_check(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    await session.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "postgresql",
    }
