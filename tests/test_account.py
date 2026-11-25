"""Recuperar/cambiar contraseña y cambiar correo.

Las pruebas de integración requieren TEST_DATABASE_URL (ver conftest.py).
"""

from app.services import email_service

EMAIL = "ana@ues.edu.sv"
PASSWORD = "Connect2026!"
NEW_PASSWORD = "OtraClave2027!"


# =====================================================
# CORREOS (sin base de datos)
# =====================================================
def test_cada_proposito_tiene_su_asunto_y_titulo():
    reset = email_service.build_code_email("a@b.com", "123456", "password_reset")
    change = email_service.build_code_email("a@b.com", "123456", "email_change")

    assert "restablecer" in reset["Subject"]
    assert "Restablece tu contraseña" in reset.get_body(("html",)).get_content()
    assert "nuevo correo" in change["Subject"]
    assert "123456" in change.get_body(("plain",)).get_content()


# =====================================================
# AUXILIARES
# =====================================================
async def register(client, email=EMAIL, password=PASSWORD) -> dict[str, str]:
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
    return await login(client, email, password)


async def login(client, email=EMAIL, password=PASSWORD) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# =====================================================
# RECUPERAR CONTRASEÑA
# =====================================================
async def test_recuperar_contrasena_con_codigo(client):
    await register(client)

    sent = await client.post("/auth/password-reset/request", json={"email": EMAIL})
    code = sent.json()["debug_code"]
    assert code

    response = await client.post(
        "/auth/password-reset/confirm",
        json={"email": EMAIL, "code": code, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text

    old = await client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert old.status_code == 401
    await login(client, EMAIL, NEW_PASSWORD)


async def test_recuperar_no_revela_si_el_correo_existe(client):
    response = await client.post(
        "/auth/password-reset/request", json={"email": "nadie@ejemplo.com"}
    )

    assert response.status_code == 200
    assert response.json()["debug_code"] is None


async def test_codigo_de_verificacion_no_sirve_para_restablecer(client):
    await register(client)
    verify = await client.post(
        "/auth/email-verification/request", json={"email": EMAIL}
    )
    verify_code = verify.json()["debug_code"]

    response = await client.post(
        "/auth/password-reset/confirm",
        json={"email": EMAIL, "code": verify_code, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400


async def test_codigo_equivocado_no_cambia_la_contrasena(client):
    await register(client)
    code = (
        await client.post("/auth/password-reset/request", json={"email": EMAIL})
    ).json()["debug_code"]

    response = await client.post(
        "/auth/password-reset/confirm",
        json={"email": EMAIL, "code": wrong(code), "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
    await login(client, EMAIL, PASSWORD)


# =====================================================
# CAMBIAR CONTRASEÑA
# =====================================================
async def test_cambiar_contrasena_exige_la_actual(client):
    headers = await register(client)

    bad = await client.post(
        "/auth/password/change",
        headers=headers,
        json={"current_password": "incorrecta", "new_password": NEW_PASSWORD},
    )
    assert bad.status_code == 400

    ok = await client.post(
        "/auth/password/change",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert ok.status_code == 200
    await login(client, EMAIL, NEW_PASSWORD)


# =====================================================
# CAMBIAR CORREO
# =====================================================
async def test_cambiar_correo_con_codigo(client):
    headers = await register(client)
    new_email = "ana.nueva@gmail.com"

    sent = await client.post(
        "/auth/email-change/request",
        headers=headers,
        json={"new_email": new_email, "password": PASSWORD},
    )
    assert sent.status_code == 200, sent.text

    confirmed = await client.post(
        "/auth/email-change/confirm",
        headers=headers,
        json={"code": sent.json()["debug_code"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["email"] == new_email

    await login(client, new_email, PASSWORD)


async def test_cambiar_correo_exige_contrasena(client):
    headers = await register(client)

    response = await client.post(
        "/auth/email-change/request",
        headers=headers,
        json={"new_email": "otro@gmail.com", "password": "incorrecta"},
    )

    assert response.status_code == 400


async def test_no_se_puede_usar_un_correo_ajeno(client):
    await register(client, email="luis@ues.edu.sv")
    headers = await register(client)

    response = await client.post(
        "/auth/email-change/request",
        headers=headers,
        json={"new_email": "luis@ues.edu.sv", "password": PASSWORD},
    )

    assert response.status_code == 409
