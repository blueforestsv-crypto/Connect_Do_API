"""Historias de 24 h. Requiere TEST_DATABASE_URL (ver conftest.py)."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.test_people_and_applications import me_id
from tests.test_publication_interactions import make_user

URL = "https://res.cloudinary.com/connectdo/image/upload/v1/connect_do/story/u/a.jpg"


@pytest.fixture(autouse=True)
def cloudinary(monkeypatch):
    from app.services import media_service

    monkeypatch.setattr(media_service.settings, "cloudinary_cloud_name", "connectdo")


async def contacts(client, a, b):
    b_id = await me_id(client, b)
    request = await client.post(f"/contacts/requests/{b_id}", headers=a)
    await client.post(f"/contacts/requests/{request.json()['id']}/accept", headers=b)


async def post_story(client, headers, caption="Hola"):
    response = await client.post(
        "/stories",
        headers=headers,
        json={"type": "image", "url": URL, "caption": caption},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_solo_contactos_ven_la_historia(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    pedro = await make_user(client, "pedro@ues.edu.sv", "Pedro")
    await contacts(client, ana, luis)
    story = await post_story(client, ana)

    luis_groups = (await client.get("/stories", headers=luis)).json()
    assert [g["user"]["first_name"] for g in luis_groups] == ["Ana"]
    assert luis_groups[0]["has_unseen"] is True

    assert (await client.get("/stories", headers=pedro)).json() == []
    hidden = await client.post(f"/stories/{story}/view", headers=pedro)
    assert hidden.status_code == 404


async def test_vistas_y_quien_la_vio(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    await contacts(client, ana, luis)
    story = await post_story(client, ana)

    await client.post(f"/stories/{story}/view", headers=luis)
    await client.post(f"/stories/{story}/view", headers=luis)  # idempotente

    mine = (await client.get("/stories", headers=ana)).json()[0]
    assert mine["is_me"] is True
    assert mine["stories"][0]["views_count"] == 1

    viewers = (await client.get(f"/stories/{story}/viewers", headers=ana)).json()
    assert [v["user"]["first_name"] for v in viewers] == ["Luis"]

    forbidden = await client.get(f"/stories/{story}/viewers", headers=luis)
    assert forbidden.status_code == 403

    luis_view = (await client.get("/stories", headers=luis)).json()[0]
    assert luis_view["has_unseen"] is False


async def test_vencidas_no_aparecen(client, monkeypatch):
    from app.api.routes import stories

    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    await post_story(client, ana)

    # 25 horas después.
    future = datetime.now(UTC) + timedelta(hours=25)
    monkeypatch.setattr(stories, "_now", lambda: future)

    assert (await client.get("/stories", headers=ana)).json() == []


async def test_borrar_mi_historia(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    story = await post_story(client, ana)

    assert (await client.delete(f"/stories/{story}", headers=luis)).status_code == 404
    assert (await client.delete(f"/stories/{story}", headers=ana)).status_code == 204
    assert (await client.get("/stories", headers=ana)).json() == []


async def test_no_acepta_enlaces_ajenos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    response = await client.post(
        "/stories",
        headers=ana,
        json={"type": "image", "url": "https://otro.com/x.jpg"},
    )
    assert response.status_code == 422
