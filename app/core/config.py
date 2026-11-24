from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Connect Do API"
    app_env: str = "development"
    app_debug: bool = True
    # Registra cada consulta SQL en el log. Muy costoso: activar solo para depurar.
    db_echo: bool = False

    # Orígenes permitidos por CORS, separados por coma.
    # Ej.: "https://panel.connect-it.com,http://localhost:3000". "*" = todos.
    cors_origins: str = "*"

    database_url: str
    refresh_token_expire_days: int = 30

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Código numérico de verificación de correo.
    email_verification_token_expire_minutes: int = 15
    email_verification_resend_seconds: int = 60
    email_verification_code_length: int = 6
    email_verification_max_attempts: int = 5

    # OAuth con Google: Client IDs aceptados como "aud" del id_token,
    # separados por coma. Debe incluir el Web Client ID que la app usa
    # como serverClientId. Vacío = inicio con Google deshabilitado.
    google_client_ids: str = ""

    # Correo saliente por SMTP (sirve con Gmail, Resend, SendGrid, Brevo...).
    # Sin SMTP_HOST, en development el código solo se escribe en el log.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # True para el puerto 465 (SSL directo); False usa STARTTLS (587).
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 15
    email_from_address: str = ""
    email_from_name: str = "Connect Do"

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.email_from_address)

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def google_client_ids_list(self) -> list[str]:
        return [cid.strip() for cid in self.google_client_ids.split(",") if cid.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
