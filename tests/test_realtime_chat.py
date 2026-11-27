"""Chat en tiempo real: hub de WebSocket, reacciones, responder citando,
eliminar para todos y grupos. Lo de base de datos requiere TEST_DATABASE_URL
(ver conftest.py)."""

import uuid

from app.services.realtime import Hub
from tests.test_people_and_applications import me_id
from tests.test_publication_interactions import make_user


class FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def send_json(self, data: dict) -> None:
        if self.fail:
            raise RuntimeError("cerrado")
        self.sent.append(data)


# Sin base de datos ------------------------------------------------------------
async def test_hub_en_linea_y_envio_a_todos_los_telefonos():
    hub = Hub()
    ana = uuid.uuid4()
    phone, tablet = FakeSocket(), FakeSocket()

    assert await hub.connect(ana, phone) is True  # pasa a "en línea"
    assert await hub.connect(ana, tablet) is False  # ya lo estaba
    await hub.send([ana], {"type": "message"})
    assert phone.sent == tablet.sent == [{"type": "message"}]

    assert hub.disconnect(ana, phone) is False  # sigue en la tableta
    assert hub.is_online(ana)
    assert hub.disconnect(ana, tablet) is True  # ahora sí desconectado
    assert not hub.is_online(ana)


async def test_hub_descarta_conexiones_caidas():
    hub = Hub()
    ana = uuid.uuid4()
    await hub.connect(ana, FakeSocket(fail=True))
    await hub.send([ana], {"type": "message"})
    assert not hub.is_online(ana)


# Con base de datos ------------------------------------------------------------
async def _contacts(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    ana_id, luis_id = await me_id(client, ana), await me_id(client, luis)
    request = await client.post(f"/contacts/requests/{luis_id}", headers=ana)
    await client.post(f"/contacts/requests/{request.json()['id']}/accept", headers=luis)
    return ana, ana_id, luis, luis_id


async def test_responder_reaccionar_y_eliminar(client):
    ana, ana_id, luis, luis_id = await _contacts(client)

    first = await client.post(
        f"/chats/{luis_id}/messages", headers=ana, json={"content": "¿Vamos?"}
    )
    reply = await client.post(
        f"/chats/{ana_id}/messages",
        headers=luis,
        json={"content": "¡Sí!", "reply_to_id": first.json()["id"]},
    )
    assert reply.json()["reply_to"]["content"] == "¿Vamos?"

    react = await client.post(
        f"/chats/messages/{first.json()['id']}/react",
        headers=luis,
        json={"emoji": "👍"},
    )
    assert react.json()["reactions"] == {luis_id: "👍"}

    # Solo quien lo envió puede eliminarlo para todos.
    forbidden = await client.delete(
        f"/chats/messages/{first.json()['id']}", headers=luis
    )
    assert forbidden.status_code == 403
    gone = await client.delete(f"/chats/messages/{first.json()['id']}", headers=ana)
    assert gone.status_code == 204

    messages = (await client.get(f"/chats/{luis_id}/messages", headers=ana)).json()
    deleted = next(m for m in messages if m["id"] == first.json()["id"])
    assert deleted["is_deleted"] is True
    assert deleted["content"] == "" and deleted["reactions"] == {}
    quoted = next(m for m in messages if m["id"] == reply.json()["id"])
    assert quoted["reply_to"]["is_deleted"] is True


async def test_grupos(client):
    ana, ana_id, luis, luis_id = await _contacts(client)
    extra = await make_user(client, "eva@ues.edu.sv", "Eva")
    eva_id = await me_id(client, extra)

    # Solo se agregan contactos: Eva no lo es.
    created = await client.post(
        "/groups", headers=ana, json={"name": "Tesis", "member_ids": [luis_id, eva_id]}
    )
    assert created.status_code == 201
    group = created.json()
    assert sorted(m["id"] for m in group["members"]) == sorted([ana_id, luis_id])
    assert group["my_role"] == "admin"

    sent = await client.post(
        f"/groups/{group['id']}/messages", headers=luis, json={"content": "Hola"}
    )
    assert sent.status_code == 201

    mine = (await client.get("/groups", headers=ana)).json()
    assert mine[0]["unread_count"] == 1
    assert (await client.get("/groups/unread-count", headers=ana)).json() == {
        "total": 1
    }
    await client.post(f"/groups/{group['id']}/read", headers=ana)
    assert (await client.get("/groups", headers=ana)).json()[0]["unread_count"] == 0

    # Luis no es admin: no puede renombrar.
    assert (
        await client.patch(
            f"/groups/{group['id']}", headers=luis, json={"name": "Otro"}
        )
    ).status_code == 403

    # Ana sale: Luis queda como admin.
    await client.delete(f"/groups/{group['id']}/members/{ana_id}", headers=ana)
    left = (await client.get(f"/groups/{group['id']}", headers=luis)).json()
    assert [m["role"] for m in left["members"]] == ["admin"]
    assert (await client.get(f"/groups/{group['id']}", headers=ana)).status_code == 404
