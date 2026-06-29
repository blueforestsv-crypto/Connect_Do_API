from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import auth_router, profiles_router, publications_router, contacts_router, chats_router, applications_router
from app.core.config import settings
from app.db.session import get_db_session
from app.api.routes import notifications_router


app = FastAPI(
    title=settings.app_name,
    description="Backend oficial de la aplicación móvil Connect Do.",
    version="0.1.0",
)

# CORS abierto temporalmente para pruebas locales con Flutter Web.
# Esto permite que Flutter en Chrome pueda consumir la API aunque use un puerto aleatorio.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
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