"""Seguir, menciones, respuestas y me gusta en comentarios, Explorar y
destacadas. Requiere TEST_DATABASE_URL (ver conftest.py)."""

import pytest

from app.schemas.publication import CommentCreate, PublicationCreate
from tests.test_people_and_applications import me_id
from tests.test_publication_interactions import make_publication, make_user

URL = "https://res.cloudinary.com/connectdo/image/upload/v1/connect_do/story/u/a.jpg"


@pytest.fixture(autouse=True)
def cloudinary(monkeypatch):
    from app.services import media_service

    monkeypatch.setattr(media_service.settings, "cloudinary_cloud_name", "connectdo")


# Sin base de datos ------------------------------------------------------------
def test_limite_de_menciones():
    import uuid

    with pytest.raises(ValueError):
        CommentCreate(text="hola", mentions=[uuid.uuid4() for _ in range(11)])
    PublicationCreate(
        title="Hola mundo",
        description="Una publicación con menciones",
        mentions=[uuid.uuid4()],
    )


# Con base de datos ------------------------------------------------------------
async def test_seguir_y_feed_de_seguidos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    luis_id = await me_id(client, luis)
    post = await make_publication(client, luis)

    assert (
        await client.post(f"/users/{luis_id}/follow", headers=ana)
    ).status_code == 204
    profile = (await client.get(f"/profiles/{luis_id}", headers=ana)).json()
    assert profile["is_following"] is True
    assert profile["followers_count"] == 1

    feed = (await client.get("/publications?following=true", headers=ana)).json()
    assert [p["id"] for p in feed] == [post]

    followers = (await client.get(f"/users/{luis_id}/followers", headers=ana)).json()
    assert [f["name"] for f in followers] == ["Ana Prueba"]

    await client.delete(f"/users/{luis_id}/follow", headers=ana)
    assert (await client.get("/publications?following=true", headers=ana)).json() == []


async def test_menciones_respuestas_y_me_gusta(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    luis_id = await me_id(client, luis)
    post = await make_publication(client, ana)

    first = await client.post(
        f"/publications/{post}/comments",
        headers=ana,
        json={"text": "Hola @Luis Prueba", "mentions": [luis_id]},
    )
    assert first.json()["mentions"] == [{"id": luis_id, "name": "Luis Prueba"}]
    notes = (await client.get("/notifications", headers=luis)).json()
    assert any(n["type"] == "mention" for n in notes)

    reply = await client.post(
        f"/publications/{post}/comments",
        headers=luis,
        json={"text": "¡Gracias!", "parent_id": first.json()["id"]},
    )
    assert reply.json()["parent_id"] == first.json()["id"]

    like = await client.post(
        f"/publications/{post}/comments/{reply.json()['id']}/like", headers=ana
    )
    assert like.json() == {"liked": True, "likes_count": 1}
    comments = (await client.get(f"/publications/{post}/comments", headers=ana)).json()
    by_id = {c["id"]: c for c in comments}
    assert by_id[reply.json()["id"]]["liked_by_me"] is True


async def test_explorar_muestra_publicaciones_publicas(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    post = await make_publication(client, luis, visibility="public")
    await make_publication(client, luis, visibility="contacts")

    data = (await client.get("/explore", headers=ana)).json()
    assert [p["id"] for p in data["publications"]] == [post]


async def test_destacadas_quedan_en_el_perfil(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    ana_id = await me_id(client, ana)
    story = (
        await client.post("/stories", headers=ana, json={"type": "image", "url": URL})
    ).json()["id"]

    created = await client.post(
        "/highlights", headers=ana, json={"title": "Viajes", "story_ids": [story]}
    )
    assert created.status_code == 201, created.text
    assert created.json()["cover_url"] == URL

    # Borrar la historia no borra el destacado.
    await client.delete(f"/stories/{story}", headers=ana)
    highlights = (await client.get(f"/users/{ana_id}/highlights", headers=ana)).json()
    assert [h["title"] for h in highlights] == ["Viajes"]
