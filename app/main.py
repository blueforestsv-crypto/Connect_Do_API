from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import auth_router, profiles_router
from app.core.config import settings
from app.db.session import get_db_session


app = FastAPI(
    title=settings.app_name,
    description="Backend oficial de la aplicación móvil Connect Do.",
    version="0.1.0",
)

app.include_router(auth_router)
app.include_router(profiles_router)


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
