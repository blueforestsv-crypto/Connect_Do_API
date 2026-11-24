import logging
import smtplib

import pytest

from app.core.config import settings
from app.services import email_service


class FakeSMTP:
    """Reemplazo de smtplib.SMTP que registra lo que se hizo."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.calls: list[str] = []
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append("quit")
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")

    def send_message(self, message):
        self.calls.append("send")
        self.sent.append(message)


@pytest.fixture
def smtp_configured(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "apikey")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_use_ssl", False)
    monkeypatch.setattr(settings, "email_from_address", "no-reply@connectdo.app")
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", FakeSMTP)


def test_mensaje_incluye_codigo_en_texto_y_html():
    message = email_service.build_verification_email("ana@utec.edu.sv", "482913")

    assert message["To"] == "ana@utec.edu.sv"
    assert "482913" in message["Subject"]

    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "482913" in plain
    assert "4 8 2 9 1 3" in html


def test_sin_smtp_en_development_solo_registra_en_log(monkeypatch, caplog):
    monkeypatch.setattr(
        email_service.smtplib,
        "SMTP",
        lambda *a, **k: pytest.fail("No debe abrir conexión SMTP"),
    )

    with caplog.at_level(logging.WARNING):
        email_service.send_verification_email("ana@utec.edu.sv", "123456")

    assert "123456" in caplog.text


def test_sin_smtp_en_produccion_no_expone_el_codigo(monkeypatch, caplog):
    monkeypatch.setattr(settings, "app_env", "production")

    with caplog.at_level(logging.WARNING):
        email_service.send_verification_email("ana@utec.edu.sv", "123456")

    assert "123456" not in caplog.text
    assert "SMTP_HOST" in caplog.text


def test_con_smtp_usa_starttls_login_y_envia(smtp_configured):
    email_service.send_verification_email("ana@utec.edu.sv", "654321")

    server = FakeSMTP.instances[-1]
    assert (server.host, server.port) == ("smtp.example.com", 587)
    assert server.calls == ["starttls", "login:apikey", "send", "quit"]
    assert "654321" in server.sent[0]["Subject"]


def test_con_ssl_no_hace_starttls(smtp_configured, monkeypatch):
    monkeypatch.setattr(settings, "smtp_use_ssl", True)
    monkeypatch.setattr(settings, "smtp_port", 465)

    email_service.send_verification_email("ana@utec.edu.sv", "654321")

    assert "starttls" not in FakeSMTP.instances[-1].calls


def test_fallo_smtp_se_registra_sin_lanzar(smtp_configured, monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise smtplib.SMTPConnectError(421, "servicio no disponible")

    monkeypatch.setattr(email_service.smtplib, "SMTP", broken)

    with caplog.at_level(logging.ERROR):
        email_service.send_verification_email("ana@utec.edu.sv", "654321")

    assert "Falló el envío" in caplog.text
