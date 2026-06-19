import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import settings


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return password_hash.verify(
        plain_password,
        hashed_password,
    )


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)

    expires_at = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )

    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": expires_at,
        "type": "access",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(
    subject: str,
    jti: str,
    expires_at: datetime,
) -> str:
    now = datetime.now(UTC)

    payload: dict[str, Any] = {
        "sub": subject,
        "jti": jti,
        "iat": now,
        "exp": expires_at,
        "type": "refresh",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    return _decode_token(
        token=token,
        expected_type="access",
        required_claims=["sub", "exp", "type"],
    )


def decode_refresh_token(token: str) -> dict[str, Any]:
    return _decode_token(
        token=token,
        expected_type="refresh",
        required_claims=["sub", "exp", "type", "jti"],
    )


def _decode_token(
    token: str,
    expected_type: str,
    required_claims: list[str],
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={
                "require": required_claims,
            },
        )
    except InvalidTokenError as error:
        raise ValueError("Token inválido o vencido.") from error

    if payload.get("type") != expected_type:
        raise ValueError("Tipo de token inválido.")

    return payload


def generate_jti() -> str:
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
