"""Configuración de pruebas.

Las pruebas unitarias no necesitan base de datos. Las de integración usan
TEST_DATABASE_URL: una base Postgres vacía y desechable (se borran y recrean
las tablas en cada prueba). Si no está definida, se omiten.
"""

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Valores mínimos para poder importar la app sin un .env real.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/unused"
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-enough-length-123")

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db_session  # noqa: E402
from app.main import app  # noqa: E402

# Registrar todos los modelos en Base.metadata.
import app.models.application  # noqa: E402,F401
import app.models.contact_request  # noqa: E402,F401
import app.models.cv_file  # noqa: E402,F401
import app.models.device_token  # noqa: E402,F401
import app.models.professional  # noqa: E402,F401
import app.models.safety  # noqa: E402,F401
import app.models.social  # noqa: E402,F401
import app.models.sticker  # noqa: E402,F401
import app.models.story  # noqa: E402,F401
import app.models.email_verification_token  # noqa: E402,F401
import app.models.message  # noqa: E402,F401
import app.models.notification  # noqa: E402,F401
import app.models.profile  # noqa: E402,F401
import app.models.publication  # noqa: E402,F401
import app.models.publication_interaction  # noqa: E402,F401
import app.models.refresh_token  # noqa: E402,F401
import app.models.user  # noqa: E402,F401


def _read_test_database_url() -> str:
    """Variable de entorno o, si no está, el archivo local .env.test
    (ignorado por git) para no tener que escribir la URL en la terminal."""
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if url:
        return url

    env_file = Path(__file__).resolve().parent.parent / ".env.test"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "TEST_DATABASE_URL":
                return value.strip().strip('"').strip("'")

    return ""


TEST_DATABASE_URL = _read_test_database_url()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    """Cada prueba arranca sin SMTP ni Google configurados, en development."""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "brevo_api_key", "")
    monkeypatch.setattr(settings, "email_from_address", "")
    monkeypatch.setattr(settings, "google_client_ids", "")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    # Nunca usar llaves reales aunque estén en un .env local.
    monkeypatch.setattr(settings, "firebase_service_account_json", "")
    monkeypatch.setattr(settings, "cloudinary_api_secret", "")
    monkeypatch.setattr(settings, "cloudinary_api_key", "")


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    if not TEST_DATABASE_URL:
        pytest.skip("Define TEST_DATABASE_URL para correr pruebas de integración.")

    test_url, main_url = make_url(TEST_DATABASE_URL), make_url(settings.database_url)
    if (test_url.host, test_url.database) == (main_url.host, main_url.database):
        pytest.exit(
            "TEST_DATABASE_URL no puede ser la misma base que DATABASE_URL: "
            "las pruebas borran todas las tablas.",
            returncode=2,
        )

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
