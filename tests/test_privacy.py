"""Privacidad, sesiones activas, descarga de datos y errores de la app.
Requiere TEST_DATABASE_URL (ver conftest.py)."""

import base64
import json

from tests.test_people_and_applications import me_id
from tests.test_publication_interactions import make_user

STORY = "https://res.cloudinary.com/connectdo/image/upload/v1/connect_do/story/u/a.jpg"


def _jti(refresh_token: str) -> str:
    payload = refresh_token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["jti"]


async def test_quien_me_puede_escribir(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    ana_id = await me_id(client, ana)

    # Por defecto solo contactos.
    denied = await client.post(
        f"/chats/{ana_id}/messages", headers=luis, json={"content": "Hola"}
    )
    assert denied.status_code == 403

    settings = await client.patch(
        "/auth/privacy", headers=ana, json={"message_privacy": "everyone"}
    )
    assert settings.json()["message_privacy"] == "everyone"
    allowed = await client.post(
        f"/chats/{ana_id}/messages", headers=luis, json={"content": "Hola"}
    )
    assert allowed.status_code in (200, 201)


async def test_historias_para_seguidores_y_ocultar_en_linea(client, monkeypatch):
    from app.services import media_service

    monkeypatch.setattr(media_service.settings, "cloudinary_cloud_name", "connectdo")
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    ana_id = await me_id(client, ana)

    await client.post("/stories", headers=ana, json={"type": "image", "url": STORY})
    await client.post(f"/users/{ana_id}/follow", headers=luis)
    # Seguidor pero no contacto: aún no la ve.
    assert (await client.get("/stories", headers=luis)).json() == []

    await client.patch(
        "/auth/privacy", headers=ana, json={"story_privacy": "followers"}
    )
    groups = (await client.get("/stories", headers=luis)).json()
    assert [g["user"]["id"] for g in groups] == [ana_id]

    await client.patch("/auth/privacy", headers=ana, json={"show_presence": False})
    presence = (await client.get(f"/chats/{ana_id}/presence", headers=luis)).json()
    assert presence == {"online": False, "last_seen_at": None}


async def test_sesiones_activas(client):
    await make_user(client, "ana@ues.edu.sv", "Ana")
    phone = await client.post(
        "/auth/login",
        headers={"X-Device-Name": "Android"},
        json={"email": "ana@ues.edu.sv", "password": "Connect2026!"},
    )
    web = await client.post(
        "/auth/login",
        headers={"X-Device-Name": "Navegador web"},
        json={"email": "ana@ues.edu.sv", "password": "Connect2026!"},
    )
    auth = {"Authorization": f"Bearer {phone.json()['access_token']}"}
    sessions = (await client.get("/auth/sessions", headers=auth)).json()
    assert {"Android", "Navegador web"} <= {s["device_name"] for s in sessions}

    keep = _jti(phone.json()["refresh_token"])
    await client.post(
        "/auth/sessions/revoke-others", headers=auth, json={"keep_jti": keep}
    )
    left = (await client.get("/auth/sessions", headers=auth)).json()
    assert [s["jti"] for s in left] == [keep]
    # La sesión del navegador ya no puede renovarse.
    refused = await client.post(
        "/auth/refresh", json={"refresh_token": web.json()["refresh_token"]}
    )
    assert refused.status_code == 401


async def test_descargar_mis_datos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    response = await client.get("/auth/account/export", headers=ana)
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    data = response.json()
    assert data["account"]["email"] == "ana@ues.edu.sv"
    assert data["account"]["privacy"]["message_privacy"] == "contacts"


async def test_errores_de_la_app(client):
    ok = await client.post(
        "/client-errors",
        json={"message": "Null check operator", "platform": "android"},
    )
    assert ok.status_code == 204
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    # Solo admins los ven.
    assert (await client.get("/admin/client-errors", headers=ana)).status_code == 403
