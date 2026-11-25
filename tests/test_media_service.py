"""Cloudinary sin red: firma, validación de enlaces y esquemas."""

import hashlib
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.publication import PublicationAuthorResponse, PublicationMediaItem
from app.services import media_service


@pytest.fixture
def cloudinary(monkeypatch):
    s = media_service.settings
    monkeypatch.setattr(s, "cloudinary_cloud_name", "connectdo")
    monkeypatch.setattr(s, "cloudinary_api_key", "123456")
    monkeypatch.setattr(s, "cloudinary_api_secret", "secreto")


def test_apagado_sin_configuracion(monkeypatch):
    monkeypatch.setattr(media_service.settings, "cloudinary_api_secret", "")
    assert media_service.is_enabled() is False
    with pytest.raises(media_service.MediaNotConfiguredError):
        media_service.sign_upload(uuid.uuid4(), "post", "image")


def test_firma_como_la_calcula_cloudinary(cloudinary):
    user = uuid.uuid4()
    signed = media_service.sign_upload(user, "chat", "audio")

    expected = hashlib.sha1(
        (
            f"allowed_formats={signed['allowed_formats']}"
            f"&folder=connect_do/chat/{user}"
            f"&timestamp={signed['timestamp']}"
            "secreto"
        ).encode()
    ).hexdigest()

    assert signed["signature"] == expected
    # El audio se sube como "video" en Cloudinary.
    assert signed["upload_url"].endswith("/connectdo/video/upload")
    assert "secreto" not in str(signed)


def test_usos_y_tipos_permitidos():
    assert media_service.allowed_kinds("avatar") == {"image"}
    assert "audio" in media_service.allowed_kinds("chat")
    assert "audio" not in media_service.allowed_kinds("post")


def test_solo_enlaces_de_nuestra_cuenta(cloudinary):
    own = "https://res.cloudinary.com/connectdo/image/upload/v1/connect_do/post/x.jpg"
    assert media_service.is_own_url(own)
    assert not media_service.is_own_url("https://otro.com/x.jpg")
    assert not media_service.is_own_url(
        "https://res.cloudinary.com/otracuenta/image/upload/x.jpg"
    )

    PublicationMediaItem(type="image", url=own)
    with pytest.raises(ValidationError):
        PublicationMediaItem(type="image", url="https://otro.com/x.jpg")
    with pytest.raises(ValidationError):
        PublicationMediaItem(type="image")


def test_publicaciones_antiguas_en_base64_siguen_validas():
    PublicationMediaItem(type="image", base64="aGVsbG8=")


def test_public_id_desde_enlace():
    url = (
        "https://res.cloudinary.com/connectdo/video/upload/"
        "v1732550000/connect_do/chat/abc/nota.m4a"
    )
    assert media_service.public_id_from_url(url) == "connect_do/chat/abc/nota"
    assert media_service.resource_type_from_url(url) == "video"


def test_el_feed_no_muestra_el_correo_del_autor():
    author = PublicationAuthorResponse(
        id=uuid.uuid4(), first_name="Ana", last_name="López", email="ana@ues.edu.sv"
    )
    assert author.email == ""
