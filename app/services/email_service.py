"""Envío de correos transaccionales por SMTP.

Funciona con cualquier proveedor que ofrezca SMTP (Gmail con contraseña de
aplicación, Resend, SendGrid, Brevo, Outlook...). Se llama desde
BackgroundTasks, así que nunca debe lanzar excepciones: los fallos se
registran en el log.
"""

import logging
import smtplib
import ssl

import httpx
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import settings


logger = logging.getLogger(__name__)


def build_verification_email(recipient: str, code: str) -> EmailMessage:
    minutes = settings.email_verification_token_expire_minutes
    spaced_code = " ".join(code)

    message = EmailMessage()
    message["Subject"] = f"{code} es tu código de Connect Do"
    message["From"] = formataddr(
        (settings.email_from_name, settings.email_from_address)
    )
    message["To"] = recipient
    message["Message-ID"] = make_msgid(domain="connectdo")

    message.set_content(
        "Hola,\n\n"
        f"Tu código para verificar tu correo en Connect Do es: {code}\n\n"
        f"Vence en {minutes} minutos. Si no creaste una cuenta, "
        "ignora este mensaje.\n\n"
        "— El equipo de Connect Do"
    )

    message.add_alternative(
        f"""\
<!doctype html>
<html lang="es">
  <body style="margin:0;padding:0;background:#F6F8FB;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
      <tr><td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:460px;background:#FFFFFF;border:1px solid #E8EDF3;border-radius:24px;">
          <tr><td style="padding:32px 28px;">
            <div style="font-size:20px;font-weight:700;color:#2563EB;margin-bottom:24px;">Connect Do</div>
            <h1 style="margin:0 0 8px;font-size:24px;line-height:1.2;color:#0F172A;">Verifica tu correo</h1>
            <p style="margin:0 0 24px;font-size:15px;line-height:1.5;color:#475569;">
              Escribe este código en la app para terminar de crear tu cuenta.
            </p>
            <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:14px;padding:18px;
                        text-align:center;font-size:32px;font-weight:700;letter-spacing:8px;color:#0F172A;">
              {spaced_code}
            </div>
            <p style="margin:24px 0 0;font-size:13px;line-height:1.5;color:#94A3B8;">
              El código vence en {minutes} minutos. Si no creaste una cuenta en
              Connect Do, puedes ignorar este mensaje.
            </p>
          </td></tr>
        </table>
        <div style="height:4px;max-width:460px;margin-top:16px;border-radius:4px;
                    background:linear-gradient(90deg,#2563EB,#22C55E);"></div>
      </td></tr>
    </table>
  </body>
</html>
""",
        subtype="html",
    )

    return message


class EmailSendError(Exception):
    pass


def _send_brevo(message: EmailMessage) -> None:
    """Envía por la API HTTPS de Brevo (no usa puertos SMTP)."""
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))

    response = httpx.post(
        settings.brevo_api_url,
        headers={
            "api-key": settings.brevo_api_key,
            "accept": "application/json",
            "content-type": "application/json",
        },
        json={
            "sender": {
                "name": settings.email_from_name,
                "email": settings.email_from_address,
            },
            "to": [{"email": message["To"]}],
            "subject": message["Subject"],
            "textContent": plain.get_content() if plain else "",
            "htmlContent": html.get_content() if html else "",
        },
        timeout=settings.email_http_timeout_seconds,
    )

    if response.status_code >= 300:
        # El cuerpo explica el motivo (remitente sin verificar, clave inválida...).
        raise EmailSendError(f"Brevo respondió {response.status_code}: {response.text}")


def _send_smtp(message: EmailMessage) -> None:
    timeout = settings.smtp_timeout_seconds
    context = ssl.create_default_context()

    if settings.smtp_use_ssl:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=timeout,
            context=context,
        )
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)

    with server:
        if not settings.smtp_use_ssl:
            server.starttls(context=context)

        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)

        server.send_message(message)


def send_verification_email(
    recipient: str,
    code: str,
) -> None:
    if not settings.email_enabled:
        if settings.is_development:
            logger.warning(
                "DEV verification email (sin SMTP) | recipient=%s | code=%s",
                recipient,
                code,
            )
        else:
            logger.error(
                "No se envió el código a %s: falta configurar BREVO_API_KEY "
                "(o SMTP_HOST) y EMAIL_FROM_ADDRESS.",
                recipient,
            )
        return

    message = build_verification_email(recipient, code)

    try:
        if settings.email_provider == "brevo":
            _send_brevo(message)
        else:
            _send_smtp(message)
        logger.info(
            "Código de verificación enviado a %s (%s)",
            recipient,
            settings.email_provider,
        )
    except (smtplib.SMTPException, OSError, httpx.HTTPError, EmailSendError):
        logger.exception(
            "Falló el envío del código de verificación a %s (%s)",
            recipient,
            settings.email_provider,
        )
