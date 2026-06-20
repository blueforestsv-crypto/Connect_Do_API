import logging
from urllib.parse import quote

from app.core.config import settings


logger = logging.getLogger(__name__)


def send_verification_email(
    recipient: str,
    token: str,
) -> None:
    verification_url = f"{settings.email_verification_url}?token={quote(token)}"

    if settings.app_env == "development":
        logger.warning(
            "DEV verification email | recipient=%s | url=%s",
            recipient,
            verification_url,
        )
        return

    raise NotImplementedError(
        "No se ha configurado un proveedor de correo para producción."
    )
