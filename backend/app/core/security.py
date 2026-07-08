from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from app.core.config import get_settings


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    full_name: str
    tenant_id: str | None
    role: str


@dataclass(frozen=True)
class DemoAccount:
    user: AuthUser
    password_hash: str


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${_b64url_encode(salt)}${_b64url_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = password_hash.split("$", 2)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    salt = _b64url_decode(salt_b64)
    expected = _b64url_decode(digest_b64)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(candidate, expected)


def _jwt_sign(message: bytes, secret_key: str) -> str:
    digest = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_token(subject: dict[str, Any], expires_in_seconds: int, token_type: str) -> str:
    settings = get_settings()
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**subject, "type": token_type, "iat": now, "exp": now + expires_in_seconds}
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature_segment = _jwt_sign(signing_input, settings.jwt_secret_key)
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = _jwt_sign(signing_input, settings.jwt_secret_key)
    if not hmac.compare_digest(signature_segment, expected_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        payload = json.loads(_b64url_decode(payload_segment))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if payload.get("exp", 0) < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    if expected_type is not None and payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    return payload


def build_demo_accounts() -> dict[str, DemoAccount]:
    settings = get_settings()
    accounts = [
        DemoAccount(
            user=AuthUser(
                id="user-root-1",
                email=settings.demo_root_email,
                full_name="SaaS Root",
                tenant_id=None,
                role="saas_root",
            ),
            password_hash=hash_password(settings.demo_root_password),
        ),
        DemoAccount(
            user=AuthUser(
                id="user-demo-admin-1",
                email=settings.demo_admin_email,
                full_name="Demo Tenant Admin",
                tenant_id="tenant-demo-1",
                role="organization_admin",
            ),
            password_hash=hash_password(settings.demo_admin_password),
        ),
    ]
    return {account.user.email: account for account in accounts}


DEMO_ACCOUNTS = build_demo_accounts()
