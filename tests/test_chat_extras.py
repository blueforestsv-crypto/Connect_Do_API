"""Documentos y ubicación (fija y en tiempo real) en el chat.
Lo de base de datos requiere TEST_DATABASE_URL (ver conftest.py)."""

import pytest

from app.services import media_service
from tests.test_realtime_chat import _contacts

DOC = "https://res.cloudinary.com/connectdo/raw/upload/v1/connect_do/chat/u/tesis.pdf"


@pytest.fixture(autouse=True)
def cloudinary(monkeypatch):
    monkeypatch.setattr(media_service.settings, "cloudinary_cloud_name", "connectdo")


# Sin base de datos ------------------------------------------------------------
def test_documentos_permitidos_y_su_public_id():
    assert media_service.is_allowed_file(DOC)
    assert not media_service.is_allowed_file(DOC.replace(".pdf", ".exe"))
    # Un documento debe subirse como "raw".
    assert not media_service.is_allowed_file(DOC.replace("/raw/", "/image/"))
    assert media_service.resource_type_from_url(DOC) == "raw"
    # En raw la extensión forma parte del public_id.
    assert media_service.public_id_from_url(DOC) == "connect_do/chat/u/tesis.pdf"


def test_la_firma_de_documentos_no_pide_formatos_a_cloudinary(monkeypatch):
    import uuid

    for key in ("cloudinary_api_key", "cloudinary_api_secret"):
        monkeypatch.setattr(media_service.settings, key, "x")
    signed = media_service.sign_upload(uuid.uuid4(), "chat", "file")
    assert signed["resource_type"] == "raw"
    assert "/raw/upload" in signed["upload_url"]
    # En raw, allowed_formats no va en la firma (Cloudinary rechazaría la
    # subida si la app lo mandara); sí se informa para filtrar en la app.
    assert "allowed_formats" not in signed["signed_fields"]
    assert "pdf" in signed["allowed_formats"]
    image = media_service.sign_upload(uuid.uuid4(), "chat", "image")
    assert "allowed_formats" in image["signed_fields"]


# Con base de datos ------------------------------------------------------------
async def test_enviar_documento(client):
    ana, ana_id, luis, luis_id = await _contacts(client)
    ok = await client.post(
        f"/chats/{luis_id}/messages",
        headers=ana,
        json={"attachment": {"type": "file", "url": DOC, "name": "Tesis final.pdf"}},
    )
    assert ok.status_code in (200, 201), ok.text
    assert ok.json()["attachment"]["name"] == "Tesis final.pdf"

    bad = await client.post(
        f"/chats/{luis_id}/messages",
        headers=ana,
        json={"attachment": {"type": "file", "url": DOC.replace(".pdf", ".exe")}},
    )
    assert bad.status_code == 422


async def test_ubicacion_fija_y_en_tiempo_real(client):
    ana, ana_id, luis, luis_id = await _contacts(client)

    fixed = await client.post(
        f"/chats/{luis_id}/messages",
        headers=ana,
        json={"attachment": {"type": "location", "lat": 13.7, "lng": -89.2}},
    )
    attachment = fixed.json()["attachment"]
    assert attachment["url"].startswith("https://www.google.com/maps?q=13.7")
    assert attachment["live_until"] is None
    # Una ubicación fija no se puede mover.
    moved = await client.patch(
        f"/chats/messages/{fixed.json()['id']}/location",
        headers=ana,
        json={"lat": 13.8, "lng": -89.3},
    )
    assert moved.status_code == 400

    live = await client.post(
        f"/chats/{luis_id}/messages",
        headers=ana,
        json={
            "attachment": {
                "type": "location",
                "lat": 13.7,
                "lng": -89.2,
                "live_minutes": 15,
            }
        },
    )
    live_id = live.json()["id"]
    assert live.json()["attachment"]["live_until"] is not None

    # Solo quien la comparte la mueve.
    other = await client.patch(
        f"/chats/messages/{live_id}/location",
        headers=luis,
        json={"lat": 1, "lng": 1},
    )
    assert other.status_code == 403
    updated = await client.patch(
        f"/chats/messages/{live_id}/location",
        headers=ana,
        json={"lat": 13.75, "lng": -89.25},
    )
    assert updated.json()["lat"] == 13.75

    stopped = await client.post(f"/chats/messages/{live_id}/location/stop", headers=ana)
    assert stopped.status_code == 200
    again = await client.patch(
        f"/chats/messages/{live_id}/location",
        headers=ana,
        json={"lat": 13.76, "lng": -89.26},
    )
    assert again.status_code == 400

    messages = (await client.get(f"/chats/{ana_id}/messages", headers=luis)).json()
    shown = next(m for m in messages if m["id"] == live_id)
    assert shown["attachment"]["lat"] == 13.75


async def test_ubicacion_en_grupo(client):
    ana, ana_id, luis, luis_id = await _contacts(client)
    group = (
        await client.post(
            "/groups", headers=ana, json={"name": "Salida", "member_ids": [luis_id]}
        )
    ).json()
    live = await client.post(
        f"/groups/{group['id']}/messages",
        headers=ana,
        json={
            "attachment": {
                "type": "location",
                "lat": 13.7,
                "lng": -89.2,
                "live_minutes": 60,
            }
        },
    )
    assert live.status_code == 201, live.text
    updated = await client.patch(
        f"/groups/messages/{live.json()['id']}/location",
        headers=ana,
        json={"lat": 13.71, "lng": -89.21},
    )
    assert updated.json()["lat"] == 13.71
