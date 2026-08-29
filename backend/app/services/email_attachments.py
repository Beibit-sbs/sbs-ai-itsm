from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import struct
from typing import Protocol
import uuid
import zipfile
import zlib

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.email_channel import EmailAttachment, EmailChannel, EmailInboundMessage


DEFAULT_ALLOWED_EXTENSIONS = [
    ".csv",
    ".doc",
    ".docx",
    ".jpeg",
    ".jpg",
    ".json",
    ".log",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
]
ALWAYS_BLOCKED_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".cpl",
    ".dll",
    ".exe",
    ".hta",
    ".iso",
    ".jar",
    ".js",
    ".jse",
    ".lnk",
    ".msi",
    ".ps1",
    ".reg",
    ".scr",
    ".vbe",
    ".vbs",
    ".wsf",
}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9А-Яа-яЁё._ -]+")
_EXECUTABLE_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"#!",
)
_ARCHIVE_EXTENSIONS = {".zip", ".jar", ".docx", ".xlsx", ".pptx"}
_MAX_ARCHIVE_ENTRIES = 1_000
_MAX_ARCHIVE_EXPANDED_BYTES = 100 * 1024 * 1024
_MAX_ARCHIVE_RATIO = 100
_MIME_BY_EXTENSION = {
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".doc": {"application/msword"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".jpeg": {"image/jpeg"},
    ".jpg": {"image/jpeg"},
    ".json": {"application/json", "text/json"},
    ".log": {"text/plain"},
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".ppt": {"application/vnd.ms-powerpoint"},
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    },
    ".txt": {"text/plain"},
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    },
    ".xml": {"application/xml", "text/xml"},
    ".zip": {"application/zip", "application/x-zip-compressed"},
}
_DLP_PATTERNS = (
    ("private_key_material", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
)


@dataclass(frozen=True)
class AttachmentInspection:
    payload: bytes
    detected_content_type: str
    security_findings: tuple[str, ...]
    sanitization_applied: bool
    blocked_reason: str | None


class AttachmentScanner(Protocol):
    """Provider-neutral malware scanner contract."""

    def scan(self, payload: bytes) -> tuple[str, str | None]: ...


class ClamAvAttachmentScanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def scan(self, payload: bytes) -> tuple[str, str | None]:
        return _clamav_scan(payload, self.settings)


def safe_attachment_name(value: str) -> str:
    leaf = Path(value.replace("\\", "/")).name.strip().strip(".")
    cleaned = _SAFE_FILENAME.sub("_", leaf)[:180].strip()
    return cleaned or "attachment.bin"


def _detect_content_type(payload: bytes, extension: str) -> str:
    if payload.startswith(b"%PDF-"):
        return "application/pdf"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"PK\x03\x04") or payload.startswith(b"PK\x05\x06"):
        if extension == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if extension == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if extension == ".pptx":
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return "application/zip"
    if payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return sorted(_MIME_BY_EXTENSION.get(extension, {"application/x-ole-storage"}))[0]
    if b"\x00" not in payload[:16_384]:
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            if extension == ".json":
                try:
                    json.loads(payload)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return "text/plain"
                return "application/json"
            if extension == ".xml" and payload.lstrip().startswith(b"<"):
                return "application/xml"
            return "text/plain"
    return "application/octet-stream"


def _archive_findings(payload: bytes, extension: str) -> list[str]:
    if extension not in _ARCHIVE_EXTENSIONS:
        return []
    findings: list[str] = []
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) > _MAX_ARCHIVE_ENTRIES:
                findings.append("archive_entry_limit_exceeded")
            expanded = 0
            names = set()
            for member in members[: _MAX_ARCHIVE_ENTRIES + 1]:
                normalized = member.filename.replace("\\", "/")
                path = PurePosixPath(normalized)
                if path.is_absolute() or ".." in path.parts:
                    findings.append("archive_path_traversal")
                if member.flag_bits & 0x1:
                    findings.append("encrypted_archive_member")
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    findings.append("archive_symlink")
                member_extension = Path(normalized).suffix.lower()
                if member_extension in ALWAYS_BLOCKED_EXTENSIONS:
                    findings.append("archive_executable_member")
                if member_extension in _ARCHIVE_EXTENSIONS:
                    findings.append("nested_archive")
                expanded += max(0, member.file_size)
                names.add(normalized)
            if expanded > _MAX_ARCHIVE_EXPANDED_BYTES:
                findings.append("archive_expanded_size_exceeded")
            if len(payload) > 0 and expanded / len(payload) > _MAX_ARCHIVE_RATIO:
                findings.append("archive_compression_ratio_exceeded")
            required_prefix = {
                ".docx": "word/",
                ".xlsx": "xl/",
                ".pptx": "ppt/",
            }.get(extension)
            if required_prefix and (
                "[Content_Types].xml" not in names
                or not any(name.startswith(required_prefix) for name in names)
            ):
                findings.append("invalid_openxml_container")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        findings.append("invalid_archive")
    return list(dict.fromkeys(findings))


def _strip_jpeg_exif(payload: bytes) -> tuple[bytes, bool]:
    if not payload.startswith(b"\xff\xd8"):
        return payload, False
    output = bytearray(payload[:2])
    offset = 2
    changed = False
    while offset + 4 <= len(payload):
        if payload[offset] != 0xFF:
            return payload, False
        marker = payload[offset + 1]
        if marker == 0xDA:
            output.extend(payload[offset:])
            return bytes(output), changed
        if marker in {0xD8, 0xD9}:
            output.extend(payload[offset : offset + 2])
            offset += 2
            continue
        segment_length = int.from_bytes(payload[offset + 2 : offset + 4], "big")
        end = offset + 2 + segment_length
        if segment_length < 2 or end > len(payload):
            return payload, False
        if marker == 0xE1:
            changed = True
        else:
            output.extend(payload[offset:end])
        offset = end
    return payload, False


def _strip_png_exif(payload: bytes) -> tuple[bytes, bool]:
    signature = b"\x89PNG\r\n\x1a\n"
    if not payload.startswith(signature):
        return payload, False
    output = bytearray(signature)
    offset = len(signature)
    changed = False
    while offset + 12 <= len(payload):
        length = int.from_bytes(payload[offset : offset + 4], "big")
        end = offset + 12 + length
        if end > len(payload):
            return payload, False
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_data = payload[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(payload[offset + 8 + length : end], "big")
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            return payload, False
        if chunk_type == b"eXIf":
            changed = True
        else:
            output.extend(payload[offset:end])
        offset = end
        if chunk_type == b"IEND":
            break
    return bytes(output), changed


def inspect_attachment_payload(
    payload: bytes,
    *,
    extension: str,
    declared_content_type: str | None,
) -> AttachmentInspection:
    findings: list[str] = []
    declared = (declared_content_type or "").split(";", 1)[0].strip().lower()
    detected = _detect_content_type(payload, extension)
    allowed_mimes = _MIME_BY_EXTENSION.get(extension, set())
    if not declared:
        findings.append("declared_mime_missing")
    elif declared not in allowed_mimes:
        findings.append("declared_mime_not_allowed_for_extension")
    if detected not in allowed_mimes:
        findings.append("content_mime_mismatch")
    if any(payload.startswith(signature) for signature in _EXECUTABLE_MAGIC):
        findings.append("executable_content_signature")
    findings.extend(_archive_findings(payload, extension))
    dlp_window = payload[:1_048_576]
    for code, pattern in _DLP_PATTERNS:
        if pattern.search(dlp_window):
            findings.append(f"dlp_{code}")

    sanitized = payload
    sanitization_applied = False
    if not findings and detected == "image/jpeg":
        sanitized, sanitization_applied = _strip_jpeg_exif(payload)
    elif not findings and detected == "image/png":
        sanitized, sanitization_applied = _strip_png_exif(payload)
    if sanitization_applied:
        findings.append("metadata_stripped")

    blocking = [item for item in findings if item != "metadata_stripped"]
    return AttachmentInspection(
        payload=sanitized,
        detected_content_type=detected,
        security_findings=tuple(dict.fromkeys(findings)),
        sanitization_applied=sanitization_applied,
        blocked_reason=(
            "Attachment security validation failed: " + ", ".join(blocking)
            if blocking
            else None
        ),
    )


def _clamav_scan(payload: bytes, settings: Settings) -> tuple[str, str | None]:
    if not settings.email_clamav_host:
        return "PENDING", "Antivirus scanner is not configured"
    try:
        with socket.create_connection(
            (settings.email_clamav_host, settings.email_clamav_port),
            timeout=10,
        ) as client:
            client.sendall(b"zINSTREAM\0")
            for offset in range(0, len(payload), 64 * 1024):
                chunk = payload[offset : offset + 64 * 1024]
                client.sendall(struct.pack(">I", len(chunk)))
                client.sendall(chunk)
            client.sendall(struct.pack(">I", 0))
            response = client.recv(4096).decode("utf-8", errors="replace")
    except OSError as exc:
        return "ERROR", f"Antivirus scan failed: {exc.__class__.__name__}"
    if response.rstrip("\0").endswith("OK"):
        return "CLEAN", None
    if "FOUND" in response:
        return "INFECTED", response[:500]
    return "ERROR", f"Unexpected antivirus response: {response[:300]}"


def _storage_root(settings: Settings) -> Path:
    return Path(settings.email_attachment_storage_path).expanduser().resolve()


def attachment_path(
    attachment: EmailAttachment,
    *,
    settings: Settings | None = None,
) -> Path:
    runtime_settings = settings or get_settings()
    if not attachment.storage_key:
        raise FileNotFoundError("Attachment content is not stored")
    root = _storage_root(runtime_settings)
    candidate = (root / attachment.storage_key).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Unsafe attachment storage key") from exc
    return candidate


def store_graph_attachments(
    db: Session,
    *,
    channel: EmailChannel,
    inbound: EmailInboundMessage,
    graph_attachments: list[dict[str, object]],
    settings: Settings | None = None,
) -> list[EmailAttachment]:
    runtime_settings = settings or get_settings()
    allowed = {
        extension.lower()
        for extension in (
            channel.allowed_attachment_extensions_json or DEFAULT_ALLOWED_EXTENSIONS
        )
    }
    stored: list[EmailAttachment] = []
    for raw in graph_attachments:
        provider_id = str(raw.get("id") or "")
        if not provider_id:
            continue
        existing = next(
            (
                item
                for item in stored
                if item.provider_attachment_id == provider_id
            ),
            None,
        )
        if existing:
            continue
        original_name = str(raw.get("name") or "attachment.bin")
        safe_name = safe_attachment_name(original_name)
        extension = Path(safe_name).suffix.lower()
        size = int(raw.get("size") or 0)
        content_type = str(raw.get("contentType") or "")[:160] or None
        item = EmailAttachment(
            id=str(uuid.uuid4()),
            tenant_id=channel.tenant_id,
            inbound_message_id=inbound.id,
            provider_attachment_id=provider_id,
            original_filename=original_name[:255],
            safe_filename=safe_name,
            content_type=content_type,
            detected_content_type=None,
            size_bytes=size,
            sha256=None,
            storage_key=None,
            is_inline=bool(raw.get("isInline")),
            content_id=str(raw.get("contentId") or "")[:255] or None,
            status="QUARANTINED",
            scan_status="PENDING",
            blocked_reason=None,
            security_findings_json="[]",
            sanitization_applied=False,
            download_count=0,
        )
        db.add(item)
        stored.append(item)

        if str(raw.get("@odata.type") or "") not in {
            "",
            "#microsoft.graph.fileAttachment",
        }:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = "Only regular file attachments are supported"
            continue
        if extension in ALWAYS_BLOCKED_EXTENSIONS:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = f"Executable attachment type {extension} is blocked"
            continue
        if extension not in allowed:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = f"Attachment type {extension or '(none)'} is not allowed"
            continue
        if size <= 0 or size > channel.max_attachment_bytes:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = (
                f"Attachment size must be between 1 and {channel.max_attachment_bytes} bytes"
            )
            continue
        encoded = raw.get("contentBytes")
        if not isinstance(encoded, str):
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = "Attachment content was not returned by Microsoft Graph"
            continue
        try:
            payload = base64.b64decode(encoded, validate=True)
        except ValueError:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = "Attachment content is not valid base64"
            continue
        if len(payload) != size or len(payload) > channel.max_attachment_bytes:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = "Attachment size does not match provider metadata"
            continue

        inspection = inspect_attachment_payload(
            payload,
            extension=extension,
            declared_content_type=content_type,
        )
        item.detected_content_type = inspection.detected_content_type
        item.security_findings_json = json.dumps(
            inspection.security_findings,
            separators=(",", ":"),
        )
        item.sanitization_applied = inspection.sanitization_applied
        if inspection.blocked_reason:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = inspection.blocked_reason
            continue
        payload = inspection.payload
        item.size_bytes = len(payload)

        digest = hashlib.sha256(payload).hexdigest()
        scope_digest = hashlib.sha256(
            (
                f"{channel.tenant_id}\0{channel.id}\0{inbound.id}"
            ).encode("utf-8")
        ).hexdigest()[:24]
        storage_key = str(
            Path(scope_digest[:2])
            / scope_digest[2:]
            / f"{digest}-{uuid.uuid4().hex[:8]}{extension}"
        ).replace("\\", "/")
        root = _storage_root(runtime_settings)
        destination = (root / storage_key).resolve()
        try:
            destination.relative_to(root)
        except ValueError:
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = "Unsafe attachment storage path"
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Keep the temporary basename short so atomic writes also work on
        # Windows hosts that still enforce the legacy MAX_PATH boundary.
        temporary = destination.with_name(f".{uuid.uuid4().hex}.part")
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        item.sha256 = digest
        item.storage_key = storage_key
        scanner: AttachmentScanner = ClamAvAttachmentScanner(runtime_settings)
        scan_status, scan_error = scanner.scan(payload)
        item.scan_status = scan_status
        if scan_status == "CLEAN":
            item.status = "STORED"
        elif scan_status == "INFECTED":
            item.status = "BLOCKED"
            item.blocked_reason = scan_error or "Malware detected"
        else:
            item.status = "QUARANTINED"
            item.blocked_reason = scan_error
    return stored


def delete_attachment_content(
    attachment: EmailAttachment,
    *,
    settings: Settings | None = None,
) -> bool:
    """Delete only a path proven to be inside the configured attachment root."""
    if not attachment.storage_key:
        return False
    path = attachment_path(attachment, settings=settings)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    attachment.storage_key = None
    return existed
