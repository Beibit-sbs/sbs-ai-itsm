"""Streaming authenticated encryption helpers for backup artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"SBSBKP1\x00"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024


def load_backup_key(path: Path) -> bytes:
    value = path.read_bytes().rstrip(b"\r\n")
    if len(value) < 32:
        raise RuntimeError("backup encryption secret must contain at least 32 bytes")
    return hashlib.sha256(b"sbs-backup-aes256-gcm-v1\x00" + value).digest()


def encrypt_file(source: Path, destination: Path, key: bytes) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite encrypted artifact: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    nonce = os.urandom(NONCE_BYTES)
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(MAGIC)
        with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
            output_stream.write(MAGIC)
            output_stream.write(nonce)
            for chunk in iter(lambda: input_stream.read(CHUNK_BYTES), b""):
                output_stream.write(encryptor.update(chunk))
            output_stream.write(encryptor.finalize())
            output_stream.write(encryptor.tag)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def decrypt_file(source: Path, destination: Path, key: bytes) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite decrypted artifact: {destination}")
    size = source.stat().st_size
    header_size = len(MAGIC) + NONCE_BYTES
    if size <= header_size + TAG_BYTES:
        raise RuntimeError("encrypted backup is truncated")
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with source.open("rb") as input_stream:
            if input_stream.read(len(MAGIC)) != MAGIC:
                raise RuntimeError("unsupported encrypted backup format")
            nonce = input_stream.read(NONCE_BYTES)
            input_stream.seek(-TAG_BYTES, os.SEEK_END)
            tag = input_stream.read(TAG_BYTES)
            input_stream.seek(header_size)
            remaining = size - header_size - TAG_BYTES
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(MAGIC)
            with temporary.open("wb") as output_stream:
                while remaining:
                    chunk = input_stream.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise RuntimeError("encrypted backup is truncated")
                    remaining -= len(chunk)
                    output_stream.write(decryptor.update(chunk))
                output_stream.write(decryptor.finalize())
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
