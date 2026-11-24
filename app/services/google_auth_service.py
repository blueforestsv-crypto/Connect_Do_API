"""Validación del id_token de Google (OAuth 2.0 / OpenID Connect).

La app obtiene el id_token con Google Sign-In y lo envía al backend.
Aquí se verifica la firma con las llaves públicas de Google y los claims
(aud, iss, exp, email_verified) antes de confiar en la identidad.
"""

from dataclasses import dataclass

import jwt
from jwt import PyJWKClient
from starlette.concurrency import run_in_threadpool

from app.core.config import settings


GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# Cachea las llaves públicas de Google (rotan cada cierto tiempo).
_jwks_client = PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)


class GoogleAuthError(Exception):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    given_name: str
    family_name: str
    picture: str | None


def _decode(token: str) -> dict:
    audiences = settings.google_client_ids_list

    if not audiences:
        raise GoogleAuthError("El inicio de sesión con Google no está configurado.")

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)

        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audiences,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
    except jwt.PyJWKClientError as exc:
        raise GoogleAuthError("No se pudieron obtener las llaves de Google.") from exc
    except jwt.InvalidTokenError as exc:
        raise GoogleAuthError("Token de Google inválido o vencido.") from exc


async def verify_google_id_token(token: str) -> GoogleIdentity:
    # PyJWKClient hace HTTP síncrono: se ejecuta fuera del event loop.
    claims = await run_in_threadpool(_decode, token)

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("Emisor del token inválido.")

    email = str(claims.get("email") or "").strip().lower()
    email_verified = claims.get("email_verified") in (True, "true")

    if not email or not email_verified:
        raise GoogleAuthError("La cuenta de Google no tiene un correo verificado.")

    local_part = email.split("@")[0]
    full_name = str(claims.get("name") or "").strip()

    given_name = str(claims.get("given_name") or "").strip()
    family_name = str(claims.get("family_name") or "").strip()

    if not given_name:
        given_name = full_name.split(" ")[0] if full_name else local_part
    if not family_name:
        rest = full_name.split(" ", 1)[1] if " " in full_name else ""
        family_name = rest or "-"

    return GoogleIdentity(
        sub=str(claims["sub"]),
        email=email,
        given_name=given_name[:100],
        family_name=family_name[:100],
        picture=claims.get("picture"),
    )
