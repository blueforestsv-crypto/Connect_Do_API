"""Bloquear, reportar, moderar, eliminar cuenta y límites anti-spam."""

import pytest
from fastapi import HTTPException

from app.core import rate_limit
from tests.test_people_and_applications import me_id
from tests.test_publication_interactions import make_publication, make_user


# =====================================================
# SIN BASE DE DATOS
# =====================================================
def test_limite_anti_spam():
    rate_limit.reset()
    for _ in range(3):
        rate_limit._check("prueba:ip:1", limit=3, window=60)
    with pytest.raises(HTTPException) as error:
        rate_limit._check("prueba:ip:1", limit=3, window=60)
    assert error.value.status_code == 429
    # Otra persona no se ve afectada.
    rate_limit._check("prueba:ip:2", limit=3, window=60)
    rate_limit.reset()


# =====================================================
# CON BASE DE DATOS (TEST_DATABASE_URL)
# =====================================================
async def _contacts(client, a, b):
    b_id = await me_id(client, b)
    request = await client.post(f"/contacts/requests/{b_id}", headers=a)
    await client.post(f"/contacts/requests/{request.json()['id']}/accept", headers=b)


async def test_bloquear_oculta_todo_en_ambos_sentidos(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    ana_id, luis_id = await me_id(client, ana), await me_id(client, luis)
    await _contacts(client, ana, luis)
    post = await make_publication(client, luis)

    assert (
        await client.post(f"/users/{luis_id}/block", headers=ana)
    ).status_code == 204

    # Ana ya no ve a Luis…
    feed = (await client.get("/publications", headers=ana)).json()
    assert post not in [p["id"] for p in feed]
    assert (await client.get(f"/profiles/{luis_id}", headers=ana)).status_code == 404
    # …ni Luis a Ana, y no pueden escribirse.
    assert (await client.get(f"/profiles/{ana_id}", headers=luis)).status_code == 404
    sent = await client.post(
        f"/chats/{ana_id}/messages", headers=luis, json={"content": "hola"}
    )
    assert sent.status_code == 403
    # Dejaron de ser contactos.
    found = (
        await client.get("/contacts/users/search", headers=luis, params={"q": "Ana"})
    ).json()
    assert found == []

    blocked = (await client.get("/users/blocked", headers=ana)).json()
    assert [b["first_name"] for b in blocked] == ["Luis"]

    await client.delete(f"/users/{luis_id}/block", headers=ana)
    assert (await client.get(f"/profiles/{luis_id}", headers=ana)).status_code == 200


async def test_reportar_y_moderar(client, monkeypatch):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    post = await make_publication(client, luis)

    report = await client.post(
        "/reports",
        headers=ana,
        json={"target_type": "publication", "target_id": post, "reason": "scam"},
    )
    assert report.status_code == 201, report.text

    # Un usuario normal no entra al panel.
    assert (await client.get("/admin/reports", headers=ana)).status_code == 403

    # Ana pasa a ser admin (en producción se hace con un UPDATE en la base).
    from app.api.dependencies import get_current_user
    from app.main import app

    real = app.dependency_overrides.get(get_current_user)

    async def as_admin(user=__import__("fastapi").Depends(get_current_user)):
        user.role = "admin"
        return user

    from app.api.routes import safety

    app.dependency_overrides[safety.require_admin] = as_admin
    try:
        pending = (await client.get("/admin/reports", headers=ana)).json()
        assert pending[0]["target_type"] == "publication"
        assert pending[0]["reason"] == "scam"

        resolved = await client.post(
            f"/admin/reports/{pending[0]['id']}/resolve",
            headers=ana,
            json={"action": "remove_content"},
        )
        assert resolved.status_code == 204
    finally:
        app.dependency_overrides.pop(safety.require_admin, None)
        if real:
            app.dependency_overrides[get_current_user] = real

    # La publicación ya no se ve.
    assert (await client.get(f"/publications/{post}", headers=ana)).status_code == 404


async def test_no_puedes_reportarte(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    ana_id = await me_id(client, ana)
    response = await client.post(
        "/reports",
        headers=ana,
        json={"target_type": "user", "target_id": ana_id, "reason": "spam"},
    )
    assert response.status_code == 400


async def test_eliminar_mi_cuenta(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    await make_publication(client, ana)

    wrong = await client.request(
        "DELETE", "/auth/account", headers=ana, json={"password": "mal"}
    )
    assert wrong.status_code == 400

    ok = await client.request(
        "DELETE", "/auth/account", headers=ana, json={"password": "Connect2026!"}
    )
    assert ok.status_code == 204

    again = await client.post(
        "/auth/login", json={"email": "ana@ues.edu.sv", "password": "Connect2026!"}
    )
    assert again.status_code == 401
