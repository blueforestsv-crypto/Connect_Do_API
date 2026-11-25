"""Me gusta y comentarios contra una base Postgres de prueba.

Requiere TEST_DATABASE_URL (ver conftest.py); si no está, se omite.
"""

import pytest


async def make_user(client, email: str, first_name: str) -> dict[str, str]:
    password = "Connect2026!"
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": "Prueba",
        },
    )
    assert response.status_code == 201, response.text

    response = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def make_publication(client, headers, visibility: str = "public") -> str:
    response = await client.post(
        "/publications",
        headers=headers,
        json={
            "type": "general",
            "title": "Busco equipo para hackatón",
            "description": "Necesitamos alguien de diseño para el fin de semana.",
            "visibility": visibility,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def feed_item(client, headers, publication_id: str) -> dict:
    response = await client.get("/publications", headers=headers)
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["id"] == publication_id)


@pytest.fixture
async def ana_y_luis(client):
    ana = await make_user(client, "ana@mail.utec.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    return ana, luis


# =====================================================
# ME GUSTA
# =====================================================
async def test_like_actualiza_contadores_y_es_por_usuario(client, ana_y_luis):
    ana, luis = ana_y_luis
    publication_id = await make_publication(client, ana)

    response = await client.post(f"/publications/{publication_id}/like", headers=luis)
    assert response.status_code == 200, response.text
    assert response.json() == {"liked": True, "likes_count": 1}

    for_luis = await feed_item(client, luis, publication_id)
    assert for_luis["likes_count"] == 1
    assert for_luis["liked_by_me"] is True
    assert for_luis["is_mine"] is False

    for_ana = await feed_item(client, ana, publication_id)
    assert for_ana["liked_by_me"] is False
    assert for_ana["is_mine"] is True


async def test_like_es_idempotente_y_se_puede_quitar(client, ana_y_luis):
    ana, luis = ana_y_luis
    publication_id = await make_publication(client, ana)
    url = f"/publications/{publication_id}/like"

    await client.post(url, headers=luis)
    again = await client.post(url, headers=luis)
    assert again.json()["likes_count"] == 1

    removed = await client.delete(url, headers=luis)
    assert removed.json() == {"liked": False, "likes_count": 0}

    removed_again = await client.delete(url, headers=luis)
    assert removed_again.json()["likes_count"] == 0


async def test_like_avisa_al_autor_una_sola_vez(client, ana_y_luis):
    ana, luis = ana_y_luis
    publication_id = await make_publication(client, ana)
    url = f"/publications/{publication_id}/like"

    await client.post(url, headers=luis)
    await client.delete(url, headers=luis)
    await client.post(url, headers=luis)

    notifications = (await client.get("/notifications", headers=ana)).json()
    likes = [n for n in notifications if n["type"] == "like"]
    assert len(likes) == 1
    assert "Luis" in likes[0]["message"]


async def test_mi_propio_like_no_me_notifica(client, ana_y_luis):
    ana, _ = ana_y_luis
    publication_id = await make_publication(client, ana)

    await client.post(f"/publications/{publication_id}/like", headers=ana)

    notifications = (await client.get("/notifications", headers=ana)).json()
    assert not [n for n in notifications if n["type"] == "like"]


async def test_no_se_puede_dar_like_a_lo_que_no_puedo_ver(client, ana_y_luis):
    ana, luis = ana_y_luis
    publication_id = await make_publication(client, ana, visibility="private")

    response = await client.post(f"/publications/{publication_id}/like", headers=luis)

    assert response.status_code == 404


# =====================================================
# COMENTARIOS
# =====================================================
async def test_comentar_listar_y_contar(client, ana_y_luis):
    ana, luis = ana_y_luis
    publication_id = await make_publication(client, ana)
    url = f"/publications/{publication_id}/comments"

    created = await client.post(url, headers=luis, json={"text": "  ¡Me apunto!  "})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["text"] == "¡Me apunto!"
    assert body["author"]["first_name"] == "Luis"
    assert body["is_mine"] is True
    assert body["can_delete"] is True

    # Para Ana (autora de la publicación): no es suyo, pero puede borrarlo.
    listed = (await client.get(url, headers=ana)).json()
    assert len(listed) == 1
    assert listed[0]["is_mine"] is False
    assert listed[0]["can_delete"] is True

    assert (await feed_item(client, ana, publication_id))["comments_count"] == 1

    notifications = (await client.get("/notifications", headers=ana)).json()
    assert any(n["type"] == "comment" for n in notifications)


@pytest.mark.parametrize("text", ["", "   ", "x" * 1001])
async def test_comentario_invalido_se_rechaza(client, ana_y_luis, text):
    ana, _ = ana_y_luis
    publication_id = await make_publication(client, ana)

    response = await client.post(
        f"/publications/{publication_id}/comments", headers=ana, json={"text": text}
    )

    assert response.status_code == 422


async def test_solo_el_autor_edita_su_comentario(client, ana_y_luis):
    ana, luis = ana_y_luis
    publication_id = await make_publication(client, ana)
    url = f"/publications/{publication_id}/comments"
    comment_id = (await client.post(url, headers=luis, json={"text": "Hola"})).json()[
        "id"
    ]

    by_ana = await client.patch(
        f"{url}/{comment_id}", headers=ana, json={"text": "Editado por Ana"}
    )
    assert by_ana.status_code == 403

    by_luis = await client.patch(
        f"{url}/{comment_id}", headers=luis, json={"text": "Hola, editado"}
    )
    assert by_luis.status_code == 200
    assert by_luis.json()["text"] == "Hola, editado"


async def test_autor_de_la_publicacion_puede_moderar_comentarios(client, ana_y_luis):
    ana, luis = ana_y_luis
    carla = await make_user(client, "carla@uca.edu.sv", "Carla")
    publication_id = await make_publication(client, ana)
    url = f"/publications/{publication_id}/comments"
    comment_id = (await client.post(url, headers=luis, json={"text": "Spam"})).json()[
        "id"
    ]

    # Una tercera persona no puede borrarlo.
    assert (
        await client.delete(f"{url}/{comment_id}", headers=carla)
    ).status_code == 403

    # La autora de la publicación sí.
    assert (await client.delete(f"{url}/{comment_id}", headers=ana)).status_code == 204
    assert (await client.get(url, headers=ana)).json() == []


# =====================================================
# PERFIL: MIS PUBLICACIONES
# =====================================================
async def test_filtro_mine_devuelve_solo_mis_publicaciones(client, ana_y_luis):
    ana, luis = ana_y_luis
    mine_public = await make_publication(client, ana)
    mine_private = await make_publication(client, ana, visibility="private")
    await make_publication(client, luis)

    response = await client.get("/publications", params={"mine": "true"}, headers=ana)

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert ids == {mine_public, mine_private}
    assert all(item["is_mine"] for item in response.json())


async def test_notificaciones_incluyen_quien_las_genero(client, ana_y_luis):
    ana, luis = ana_y_luis
    publication_id = await make_publication(client, ana)
    await client.post(f"/publications/{publication_id}/like", headers=luis)

    notifications = (await client.get("/notifications", headers=ana)).json()
    like = next(n for n in notifications if n["type"] == "like")

    assert like["related_user"]["first_name"] == "Luis"
    assert like["related_publication_id"] == publication_id
