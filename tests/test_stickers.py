"""Colección de stickers."""

import pytest
from pydantic import ValidationError

from app.schemas.chat import MessageCreate
from app.services import media_service
from tests.test_publication_interactions import make_user

URL = "https://res.cloudinary.com/connectdo/image/upload/v1/connect_do/sticker/u/gato.webp"


@pytest.fixture(autouse=True)
def cloudinary(monkeypatch):
    monkeypatch.setattr(media_service.settings, "cloudinary_cloud_name", "connectdo")


# Sin base de datos ------------------------------------------------------------
def test_se_puede_enviar_un_sticker_en_el_chat():
    message = MessageCreate(attachment={"type": "sticker", "url": URL})
    assert message.attachment.type == "sticker"


def test_sticker_con_enlace_ajeno_no_vale():
    with pytest.raises(ValidationError):
        MessageCreate(attachment={"type": "sticker", "url": "https://otro.com/a.webp"})


def test_los_stickers_solo_aceptan_imagenes():
    assert media_service.allowed_kinds("sticker") == {"image"}


# Con base de datos (TEST_DATABASE_URL) ----------------------------------------
async def test_guardar_y_borrar_stickers(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")

    first = await client.post("/stickers", headers=ana, json={"url": URL})
    assert first.status_code == 201, first.text
    # Guardarlo dos veces no lo duplica.
    again = await client.post("/stickers", headers=ana, json={"url": URL})
    assert again.json()["id"] == first.json()["id"]

    mine = (await client.get("/stickers", headers=ana)).json()
    assert [s["url"] for s in mine] == [URL]

    await client.delete(f"/stickers/{first.json()['id']}", headers=ana)
    assert (await client.get("/stickers", headers=ana)).json() == []


async def test_cada_quien_ve_solo_sus_stickers(client):
    ana = await make_user(client, "ana@ues.edu.sv", "Ana")
    luis = await make_user(client, "luis@ues.edu.sv", "Luis")
    await client.post("/stickers", headers=ana, json={"url": URL})

    assert (await client.get("/stickers", headers=luis)).json() == []
