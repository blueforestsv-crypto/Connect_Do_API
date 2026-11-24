from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    # Verifica la conexión antes de usarla (Neon cierra conexiones inactivas).
    pool_pre_ping=True,
    # Recicla conexiones antes de que Neon las corte por inactividad / suspensión.
    pool_recycle=300,
    pool_size=5,
    max_overflow=5,
    # Tiempo máximo esperando una conexión libre del pool.
    pool_timeout=30,
    connect_args={
        # Neon puede tardar unos segundos en despertar tras suspenderse.
        "timeout": 15,
        # Evita que una consulta colgada bloquee la petición indefinidamente.
        "command_timeout": 30,
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
