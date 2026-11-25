"""Push con Firebase, sin red: se simula Google con httpx.MockTransport."""

import json
import uuid
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import push_service


@pytest.fixture
def fake_firebase(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    account = {
        "project_id": "connect-do-test",
        "client_email": "push@connect-do-test.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setattr(
        push_service.settings, "firebase_service_account_json", json.dumps(account)
    )
    push_service._service_account.cache_clear()
    monkeypatch.setattr(push_service, "_access_token", None)
    yield key.public_key()
    push_service._service_account.cache_clear()


def test_sin_configuracion_esta_apagado(monkeypatch):
    monkeypatch.setattr(push_service.settings, "firebase_service_account_json", "")
    push_service._service_account.cache_clear()
    assert push_service.is_enabled() is False


def test_json_invalido_no_rompe(monkeypatch):
    monkeypatch.setattr(
        push_service.settings, "firebase_service_account_json", "{no es json"
    )
    push_service._service_account.cache_clear()
    assert push_service.is_enabled() is False
    push_service._service_account.cache_clear()


def test_notificacion_a_push():
    user_id = uuid.uuid4()
    publication_id = uuid.uuid4()
    notification = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        type="like",
        title="Nuevo me gusta",
        message="A Ana le gusta tu publicación.",
        related_user_id=None,
        related_publication_id=publication_id,
        related_message_id=None,
        related_contact_request_id=None,
    )

    push = push_service.push_from_notification(notification)
    message = push_service.build_fcm_message("token-123", push)["message"]

    assert push.user_id == user_id
    assert message["notification"]["title"] == "Nuevo me gusta"
    assert message["data"]["type"] == "like"
    assert message["data"]["related_publication_id"] == str(publication_id)
    assert "related_user_id" not in message["data"]
    # FCM exige que todos los valores de data sean texto.
    assert all(isinstance(v, str) for v in message["data"].values())
    assert message["android"]["notification"]["channel_id"] == (
        push_service.ANDROID_CHANNEL_ID
    )


def test_detecta_tokens_muertos():
    def response(status, text=""):
        return httpx.Response(status, text=text)

    assert push_service._is_dead_token(response(404))
    assert push_service._is_dead_token(response(400, '{"errorCode":"UNREGISTERED"}'))
    assert not push_service._is_dead_token(response(500))
    assert not push_service._is_dead_token(response(200))


async def test_token_de_google_firmado_y_reutilizado(fake_firebase):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        form = dict(pair.split("=", 1) for pair in request.content.decode().split("&"))
        claims = jwt.decode(
            form["assertion"],
            fake_firebase,
            algorithms=["RS256"],
            audience="https://oauth2.googleapis.com/token",
        )
        assert claims["scope"] == push_service.FCM_SCOPE
        assert claims["iss"].startswith("push@")
        return httpx.Response(200, json={"access_token": "ya29.x", "expires_in": 3600})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await push_service._get_access_token(client)
        second = await push_service._get_access_token(client)

    assert first == second == "ya29.x"
    assert len(calls) == 1  # el segundo se reutiliza
