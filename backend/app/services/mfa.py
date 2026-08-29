from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, get_settings


_AAD = b"sbs-ai-itsm-mfa-v1"
_TOTP_PERIOD_SECONDS = 30
_TOTP_DIGITS = 6


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _key(settings: Settings | None = None) -> bytes:
    runtime_settings = settings or get_settings()
    material = runtime_settings.mfa_encryption_key
    if not material and runtime_settings.demo_mode:
        return hashlib.sha256(runtime_settings.jwt_secret_key.encode("utf-8")).digest()
    if not material or len(material) < 32:
        raise RuntimeError("MFA encryption key is not configured")
    return hashlib.sha256(material.encode("utf-8")).digest()


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def encrypt_totp_secret(secret: str, settings: Settings | None = None) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key(settings)).encrypt(nonce, secret.encode("ascii"), _AAD)
    return _b64url_encode(nonce + ciphertext)


def decrypt_totp_secret(ciphertext: str, settings: Settings | None = None) -> str:
    payload = _b64url_decode(ciphertext)
    if len(payload) < 29:
        raise ValueError("Invalid MFA secret ciphertext")
    plaintext = AESGCM(_key(settings)).decrypt(payload[:12], payload[12:], _AAD)
    return plaintext.decode("ascii")


def build_otpauth_uri(secret: str, email: str, issuer: str) -> str:
    label = quote(f"{issuer}:{email}", safe="")
    query_issuer = quote(issuer, safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={query_issuer}"
        f"&algorithm=SHA1&digits={_TOTP_DIGITS}&period={_TOTP_PERIOD_SECONDS}"
    )


def _totp_at_step(secret: str, step: int) -> str:
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)


def current_totp(secret: str, *, at_time: int | None = None) -> str:
    timestamp = int(time.time()) if at_time is None else at_time
    return _totp_at_step(secret, timestamp // _TOTP_PERIOD_SECONDS)


def verify_totp(
    secret: str,
    code: str,
    *,
    last_used_step: int | None = None,
    at_time: int | None = None,
) -> int | None:
    normalized = code.strip().replace(" ", "")
    if len(normalized) != _TOTP_DIGITS or not normalized.isdigit():
        return None
    timestamp = int(time.time()) if at_time is None else at_time
    current_step = timestamp // _TOTP_PERIOD_SECONDS
    for candidate_step in (current_step - 1, current_step, current_step + 1):
        if last_used_step is not None and candidate_step <= last_used_step:
            continue
        if hmac.compare_digest(_totp_at_step(secret, candidate_step), normalized):
            return candidate_step
    return None


def generate_recovery_codes(count: int = 10) -> list[str]:
    codes: list[str] = []
    for _ in range(count):
        raw = base64.b32encode(secrets.token_bytes(12)).decode("ascii").rstrip("=")
        codes.append("-".join(raw[index : index + 5] for index in range(0, 20, 5)))
    return codes


def _normalize_recovery_code(code: str) -> str:
    return "".join(char for char in code.upper() if char.isalnum())


def hash_recovery_code(code: str, settings: Settings | None = None) -> str:
    return hmac.new(
        _key(settings),
        _normalize_recovery_code(code).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def encode_recovery_code_hashes(codes: list[str], settings: Settings | None = None) -> str:
    return json.dumps([hash_recovery_code(code, settings) for code in codes])


def consume_recovery_code(
    hashes_json: str,
    code: str,
    settings: Settings | None = None,
) -> tuple[bool, str]:
    try:
        stored_hashes = list(json.loads(hashes_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        stored_hashes = []
    candidate = hash_recovery_code(code, settings)
    matched_index = next(
        (
            index
            for index, stored_hash in enumerate(stored_hashes)
            if isinstance(stored_hash, str) and hmac.compare_digest(stored_hash, candidate)
        ),
        None,
    )
    if matched_index is None:
        return False, hashes_json
    stored_hashes.pop(matched_index)
    return True, json.dumps(stored_hashes)


def count_recovery_codes(hashes_json: str) -> int:
    try:
        values = json.loads(hashes_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0
    return len(values) if isinstance(values, list) else 0


def create_challenge_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_challenge_token(token)


def hash_challenge_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def is_locked(locked_until: datetime | None) -> bool:
    if locked_until is None:
        return False
    normalized = locked_until.replace(tzinfo=UTC) if locked_until.tzinfo is None else locked_until
    return normalized > datetime.now(UTC)
