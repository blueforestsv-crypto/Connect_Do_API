"""Flujo completo de autenticación contra una base Postgres de prueba.

Requiere TEST_DATABASE_URL (ver conftest.py); si no está, se omite.
"""

import pytest

from app.api.routes import auth as auth_routes
from app.core.config import settings
from app.services.google_auth_service import GoogleAuthError, GoogleIdentity

EMAIL = "ana.lopez@mail.utec.edu.sv"
PASSWORD = "Connect2026!"


async def register_and_login(client, email=EMAIL, password=PASSWORD) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": "Ana",
            "last_name": "López",
        },
    )
    assert response.status_code == 201, response.text

    response = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def request_code(client, email=EMAIL) -> str | None:
    response = await client.post(
        "/auth/email-verification/request", json={"email": email}
    )
    assert response.status_code == 200, response.text
    return response.json()["debug_code"]


async def confirm(client, token: str, code: str):
    return await client.post(
        "/auth/email-verification/confirm",
        json={"code": code},
        headers={"Authorization": f"Bearer {token}"},
    )


async def me(client, token: str) -> dict:
    response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# =====================================================
# VERIFICACIÓN CON CÓDIGO
# =====================================================
async def test_registro_y_verificacion_con_codigo(client):
    token = await register_and_login(client)
    assert (await me(client, token))["is_verified"] is False

    code = await request_code(client)
    assert code is not None and len(code) == 6

    response = await confirm(client, token, code)

    assert response.status_code == 200, response.text
    assert response.json()["is_verified"] is True
    assert (await me(client, token))["is_verified"] is True


async def test_codigo_incorrecto_se_rechaza(client):
    token = await register_and_login(client)
    code = await request_code(client)

    response = await confirm(client, token, wrong(code))

    assert response.status_code == 400
    assert (await me(client, token))["is_verified"] is False


async def test_tras_maximo_de_intentos_el_codigo_queda_anulado(client, monkeypatch):
    monkeypatch.setattr(settings, "email_verification_max_attempts", 3)
    token = await register_and_login(client)
    code = await request_code(client)

    for _ in range(3):
        assert (await confirm(client, token, wrong(code))).status_code == 400

    # Ni el código correcto sirve ya: hay que pedir otro.
    assert (await confirm(client, token, code)).status_code == 400


async def test_reenvio_respeta_espera_y_anula_el_codigo_anterior(client, monkeypatch):
    token = await register_and_login(client)
    first = await request_code(client)

    # Dentro de la espera no se emite otro código.
    assert await request_code(client) is None

    monkeypatch.setattr(settings, "email_verification_resend_seconds", 0)
    second = await request_code(client)
    assert second is not None

    if second != first:
        assert (await confirm(client, token, first)).status_code == 400
    assert (await confirm(client, token, second)).status_code == 200


async def test_solicitud_no_revela_si_el_correo_existe(client):
    response = await client.post(
        "/auth/email-verification/request",
        json={"email": "nadie@ejemplo.com"},
    )

    assert response.status_code == 200
    assert response.json()["debug_code"] is None


async def test_con_smtp_configurado_no_se_devuelve_debug_code(client, monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "email_from_address", "no-reply@connectdo.app")
    monkeypatch.setattr(
        auth_routes,
        "send_verification_email",
        lambda recipient, code: sent.append((recipient, code)),
    )
    await register_and_login(client)

    assert await request_code(client) is None
    assert sent and sent[0][0] == EMAIL


async def test_confirmar_requiere_sesion(client):
    response = await client.post(
        "/auth/email-verification/confirm", json={"code": "123456"}
    )

    assert response.status_code in (401, 403)


# =====================================================
# OAUTH CON GOOGLE
# =====================================================
def fake_google(monkeypatch, identity: GoogleIdentity | Exception):
    async def verify(token: str) -> GoogleIdentity:
        if isinstance(identity, Exception):
            raise identity
        return identity

    monkeypatch.setattr(auth_routes, "verify_google_id_token", verify)


GOOGLE_ANA = GoogleIdentity(
    sub="google-sub-1",
    email=EMAIL,
    given_name="Ana",
    family_name="López",
    picture="https://example.com/ana.jpg",
)


async def google_login(client):
    return await client.post("/auth/google", json={"id_token": "x" * 40})


async def test_google_crea_cuenta_verificada_y_luego_inicia_sesion(client, monkeypatch):
    fake_google(monkeypatch, GOOGLE_ANA)

    first = await google_login(client)
    assert first.status_code == 200, first.text
    assert first.json()["is_new_user"] is True

    user = await me(client, first.json()["access_token"])
    assert user["email"] == EMAIL
    assert user["is_verified"] is True

    second = await google_login(client)
    assert second.json()["is_new_user"] is False
    assert (await me(client, second.json()["access_token"]))["id"] == user["id"]


async def test_google_vincula_cuenta_existente_por_correo(client, monkeypatch):
    token = await register_and_login(client)
    original_id = (await me(client, token))["id"]
    fake_google(monkeypatch, GOOGLE_ANA)

    response = await google_login(client)

    assert response.json()["is_new_user"] is False
    linked = await me(client, response.json()["access_token"])
    assert linked["id"] == original_id
    assert linked["is_verified"] is True

    # La contraseña sigue funcionando.
    login = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert login.status_code == 200


async def test_cuenta_solo_google_no_acepta_login_con_contrasena(client, monkeypatch):
    fake_google(monkeypatch, GOOGLE_ANA)
    await google_login(client)

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": "cualquier-cosa"}
    )

    assert response.status_code == 401


async def test_google_token_invalido_devuelve_401(client, monkeypatch):
    fake_google(monkeypatch, GoogleAuthError("Token de Google inválido o vencido."))

    response = await google_login(client)

    assert response.status_code == 401
    assert "inválido" in response.json()["detail"]


@pytest.mark.parametrize("payload", [{}, {"id_token": "corto"}])
async def test_google_valida_el_cuerpo(client, payload):
    response = await client.post("/auth/google", json=payload)

    assert response.status_code == 422
