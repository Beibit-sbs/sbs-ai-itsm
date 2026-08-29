from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, get_settings


_VERSION = "v1"


def _key(settings: Settings | None = None) -> bytes:
    runtime_settings = settings or get_settings()
    material = runtime_settings.credential_encryption_key
    if not material and runtime_settings.demo_mode:
        material = f"demo:{runtime_settings.jwt_secret_key}:credential-vault"
    if not material or len(material) < 32:
        raise RuntimeError("Credential encryption key is not configured")
    return hashlib.sha256(material.encode("utf-8")).digest()


def _aad(*, purpose: str, tenant_id: str) -> bytes:
    return f"sbs-ai-itsm:{_VERSION}:{tenant_id}:{purpose}".encode("utf-8")


def encrypt_credential(
    value: str,
    *,
    purpose: str,
    tenant_id: str,
    settings: Settings | None = None,
) -> str:
    if not value:
        raise ValueError("Credential value cannot be empty")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key(settings)).encrypt(
        nonce,
        value.encode("utf-8"),
        _aad(purpose=purpose, tenant_id=tenant_id),
    )
    payload = base64.urlsafe_b64encode(nonce + ciphertext).rstrip(b"=").decode("ascii")
    return f"{_VERSION}.{payload}"


def decrypt_credential(
    value: str,
    *,
    purpose: str,
    tenant_id: str,
    settings: Settings | None = None,
) -> str:
    try:
        version, encoded = value.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid encrypted credential") from exc
    if version != _VERSION:
        raise ValueError("Unsupported encrypted credential version")
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if len(raw) < 29:
        raise ValueError("Invalid encrypted credential")
    plaintext = AESGCM(_key(settings)).decrypt(
        raw[:12],
        raw[12:],
        _aad(purpose=purpose, tenant_id=tenant_id),
    )
    return plaintext.decode("utf-8")
