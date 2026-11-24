import uuid

from app.core.config import settings
from app.services import email_verification_service as service


def test_codigo_tiene_la_longitud_configurada_y_solo_digitos(monkeypatch):
    monkeypatch.setattr(settings, "email_verification_code_length", 6)

    codes = {service._generate_code() for _ in range(200)}

    assert all(len(code) == 6 and code.isdigit() for code in codes)
    # Incluye ceros a la izquierda y no se repite siempre el mismo.
    assert len(codes) > 150


def test_mismo_codigo_en_dos_registros_produce_hashes_distintos():
    first, second = uuid.uuid4(), uuid.uuid4()

    assert service._hash_code(first, "123456") != service._hash_code(second, "123456")
    assert service._hash_code(first, "123456") == service._hash_code(first, "123456")
