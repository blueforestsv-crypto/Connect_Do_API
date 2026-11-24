import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.services import google_auth_service as google

CLIENT_ID = "web-client.apps.googleusercontent.com"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def fake_google_keys(monkeypatch, rsa_key):
    """Sustituye la descarga de llaves de Google por una llave local."""

    class SigningKey:
        key = rsa_key.public_key()

    monkeypatch.setattr(
        google._jwks_client,
        "get_signing_key_from_jwt",
        lambda token: SigningKey(),
    )
    monkeypatch.setattr(settings, "google_client_ids", CLIENT_ID)


def make_token(rsa_key, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "iat": now,
        "exp": now + 600,
        "email": "Ana.Lopez@Mail.UTEC.edu.sv",
        "email_verified": True,
        "given_name": "Ana",
        "family_name": "López",
        "picture": "https://example.com/ana.jpg",
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, rsa_key, algorithm="RS256")


async def test_token_valido_devuelve_identidad(rsa_key):
    identity = await google.verify_google_id_token(make_token(rsa_key))

    assert identity.sub == "1234567890"
    assert identity.email == "ana.lopez@mail.utec.edu.sv"
    assert (identity.given_name, identity.family_name) == ("Ana", "López")
    assert identity.picture == "https://example.com/ana.jpg"


async def test_sin_nombres_separados_usa_name(rsa_key):
    token = make_token(
        rsa_key, given_name=None, family_name=None, name="Luis Pérez Gómez"
    )

    identity = await google.verify_google_id_token(token)

    assert (identity.given_name, identity.family_name) == ("Luis", "Pérez Gómez")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"aud": "otro-cliente"}, "inválido"),
        ({"exp": int(time.time()) - 3600}, "inválido"),
        ({"iss": "https://evil.example.com"}, "Emisor"),
        ({"email_verified": False}, "verificado"),
        ({"email": None}, "verificado"),
    ],
)
async def test_tokens_invalidos_se_rechazan(rsa_key, overrides, message):
    with pytest.raises(google.GoogleAuthError, match=message):
        await google.verify_google_id_token(make_token(rsa_key, **overrides))


async def test_firma_de_otra_llave_se_rechaza():
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(google.GoogleAuthError):
        await google.verify_google_id_token(make_token(other_key))


async def test_sin_client_ids_esta_deshabilitado(rsa_key, monkeypatch):
    monkeypatch.setattr(settings, "google_client_ids", "")

    with pytest.raises(google.GoogleAuthError, match="no está configurado"):
        await google.verify_google_id_token(make_token(rsa_key))
