"""Guardadas, perfil privado y búsqueda.

Requiere TEST_DATABASE_URL (ver conftest.py); si no está, se omite.
"""

from tests.test_people_and_applications import me_id
from tests.test_publication_interactions import make_publication, make_user


async def feed_ids(client, headers, **params) -> list[str]:
    response = await client.get("/publications", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()]


# =====================================================
# GUARDADAS
# =====================================================
async def test_guardar_y_quitar(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    post = await make_publication(client, luis)

    saved = await client.put(f"/publications/{post}/save", headers=ana)
    assert saved.json() == {"saved": True}
    assert await feed_ids(client, ana, saved="true") == [post]

    item = next(
        p
        for p in (await client.get("/publications", headers=ana)).json()
        if p["id"] == post
    )
    assert item["saved_by_me"] is True
    # Es por usuario: Luis no la tiene guardada.
    assert await feed_ids(client, luis, saved="true") == []

    await client.delete(f"/publications/{post}/save", headers=ana)
    assert await feed_ids(client, ana, saved="true") == []


# =====================================================
# PERFIL PRIVADO
# =====================================================
async def test_perfil_privado_oculta_datos_y_publicaciones(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    ana_id = await me_id(client, ana)

    await client.patch(
        "/profiles/me",
        headers=ana,
        json={"bio": "Me gusta Flutter", "is_private": True},
    )
    post = await make_publication(client, ana)

    profile = (await client.get(f"/profiles/{ana_id}", headers=luis)).json()
    assert profile["limited"] is True
    assert profile["bio"] is None

    # Su publicación "pública" no le aparece a un desconocido…
    assert post not in await feed_ids(client, luis)
    detail = await client.get(f"/publications/{post}", headers=luis)
    assert detail.status_code == 404

    # …pero ella sí la ve.
    assert post in await feed_ids(client, ana)


async def test_perfil_privado_se_abre_a_contactos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    ana_id = await me_id(client, ana)
    await client.patch("/profiles/me", headers=ana, json={"is_private": True})
    post = await make_publication(client, ana)

    request = await client.post(f"/contacts/requests/{ana_id}", headers=luis)
    request_id = request.json()["id"]
    await client.post(f"/contacts/requests/{request_id}/accept", headers=ana)

    profile = (await client.get(f"/profiles/{ana_id}", headers=luis)).json()
    assert profile["limited"] is False
    assert profile["email"] == "ana@ues.edu.sv"
    assert post in await feed_ids(client, luis)


# =====================================================
# BÚSQUEDA
# =====================================================
async def test_buscar_publicaciones_por_texto(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    post = await make_publication(client, ana)  # "Busco equipo para hackatón"

    assert await feed_ids(client, ana, q="hackatón") == [post]
    assert await feed_ids(client, ana, q="no-existe-xyz") == []


async def test_buscar_personas_no_revela_correos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    await make_user(client, "luis@ues.edu.sv", "Luis")

    found = (
        await client.get("/contacts/users/search", headers=ana, params={"q": "lui"})
    ).json()
    assert [u["first_name"] for u in found] == ["Luis"]
    assert found[0]["email"] == ""

    # El correo parcial no sirve para encontrar a nadie.
    partial = (
        await client.get("/contacts/users/search", headers=ana, params={"q": "ues.edu"})
    ).json()
    assert partial == []
