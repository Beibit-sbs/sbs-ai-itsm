from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
import uuid
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.email_channel import (
    EmailAttachment,
    EmailChannel,
    EmailConversation,
)
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.services.credential_crypto import decrypt_credential, encrypt_credential
from app.services.email_operations import (
    ingest_graph_message,
    persist_graph_notifications,
    process_outbound_queue,
    queue_email,
)
from app.services.email_attachments import inspect_attachment_payload
from app.services.microsoft_graph_email import GraphSendResult


def _login(client: TestClient, email: str, password: str = "Sbs!2026") -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        demo_mode=True,
        credential_encryption_key=(
            "email-tests-use-a-dedicated-credential-encryption-key-2026"
        ),
        email_attachment_storage_path=str(tmp_path / "attachments"),
    )


def _tenant_and_channel(db_session, tmp_path: Path, *, provider: str = "MICROSOFT_GRAPH"):
    settings = _settings(tmp_path)
    tenant = Tenant(
        id=str(uuid.uuid4()),
        name="Email Test Tenant",
        slug=f"email-test-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db_session.add(tenant)
    db_session.flush()
    channel_id = str(uuid.uuid4())
    channel = EmailChannel(
        id=channel_id,
        tenant_id=tenant.id,
        name="Service Desk Mail",
        provider_type=provider,
        status="ACTIVE",
        mailbox_address="support@example.test",
        mailbox_user_id="support@example.test",
        entra_tenant_id="11111111-1111-1111-1111-111111111111",
        client_id="22222222-2222-2222-2222-222222222222",
        client_secret_encrypted=encrypt_credential(
            "graph-client-secret-value",
            purpose=f"email-channel:{channel_id}:client-secret",
            tenant_id=tenant.id,
            settings=settings,
        ),
        inbound_enabled=True,
        outbound_enabled=True,
        default_target="TICKET",
        allowed_sender_domains_json=[],
        allowed_attachment_extensions_json=[".pdf", ".txt"],
        max_attachment_bytes=2 * 1024 * 1024,
        loop_token_encrypted=encrypt_credential(
            "email-loop-token",
            purpose=f"email-channel:{channel_id}:loop-token",
            tenant_id=tenant.id,
            settings=settings,
        ),
        success_count=0,
        failure_count=0,
        version=1,
    )
    db_session.add(channel)
    db_session.flush()
    return settings, tenant, channel


def _graph_message(
    message_id: str,
    *,
    sender: str = "requester@example.test",
    subject: str = "Cannot connect to Wi-Fi",
    body: str = "Please help with the office wireless network.",
    conversation_id: str = "graph-conversation-1",
    headers: list[dict[str, str]] | None = None,
    has_attachments: bool = False,
) -> dict:
    return {
        "id": message_id,
        "conversationId": conversation_id,
        "internetMessageId": f"<{message_id}@example.test>",
        "subject": subject,
        "from": {
            "emailAddress": {
                "name": "Email Requester",
                "address": sender,
            }
        },
        "toRecipients": [
            {
                "emailAddress": {
                    "name": "Service Desk",
                    "address": "support@example.test",
                }
            }
        ],
        "ccRecipients": [],
        "receivedDateTime": datetime.now(UTC).isoformat(),
        "body": {"contentType": "HTML", "content": f"<p>{body}</p>"},
        "hasAttachments": has_attachments,
        "internetMessageHeaders": headers or [],
    }


class _AttachmentGraph:
    def __init__(self, attachments: list[dict]):
        self.attachments = attachments

    def list_attachments(self, _message_id: str) -> list[dict]:
        return self.attachments


class _SuccessfulGraph:
    def __init__(self, _channel, *, settings=None):
        self.settings = settings

    def send_mail(self, **_kwargs) -> GraphSendResult:
        return GraphSendResult(
            request_id="graph-request-accepted",
            accepted_at=datetime.now(UTC),
        )


def test_admin_can_configure_explicitly_simulated_mock_channel(app) -> None:
    with TestClient(app) as client:
        token = _login(client, "admin@sbs.local")
        created = client.post(
            "/api/v1/email/channels",
            headers=_headers(token),
            json={
                "name": "Local acceptance channel",
                "provider_type": "MOCK",
                "mailbox_address": "support@example.test",
                "inbound_enabled": True,
                "outbound_enabled": True,
                "default_target": "TICKET",
                "allowed_sender_domains": ["example.test"],
                "allowed_attachment_extensions": [".pdf", ".txt"],
                "max_attachment_bytes": 1_048_576,
            },
        )
        assert created.status_code == 201, created.text
        channel = created.json()
        assert channel["status"] == "DRAFT"
        assert channel["client_secret_configured"] is False
        assert "client_secret_encrypted" not in channel

        tested = client.post(
            f"/api/v1/email/channels/{channel['id']}/test-connection",
            headers=_headers(token),
        )
        assert tested.status_code == 200, tested.text
        assert tested.json()["ok"] is False
        assert tested.json()["status"] == "SIMULATED"
        activated = client.post(
            f"/api/v1/email/channels/{channel['id']}/state",
            headers=_headers(token),
            json={
                "expected_version": channel["version"],
                "action": "ACTIVATE",
                "reason": "Acceptance test",
            },
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["status"] == "ACTIVE"
        assert activated.json()["last_success_at"] is None

        queued = client.post(
            f"/api/v1/email/channels/{channel['id']}/test-email",
            headers=_headers(token),
            json={
                "to_email": "recipient@example.test",
                "subject": "Acceptance email",
                "body": "Queued through the configured channel.",
            },
        )
        assert queued.status_code == 202, queued.text
        assert queued.json()["status"] == "SIMULATED"


def test_mock_email_never_creates_transport_success(
    db_session,
    tmp_path: Path,
) -> None:
    settings, tenant, channel = _tenant_and_channel(
        db_session,
        tmp_path,
        provider="MOCK",
    )
    item = queue_email(
        db_session,
        to_email="recipient@example.test",
        subject="Local preview",
        body="This message must remain a simulation.",
        tenant_id=tenant.id,
        idempotency_key="mock-email-simulation",
        settings=settings,
    )
    db_session.flush()
    assert item.status == "SIMULATED"
    assert item.provider_message_id is None
    assert item.accepted_at is None
    assert item.sent_at is None
    assert item.delivered_at is None
    assert item.attempt_count == 0
    assert "no external email" in (item.error_message or "").lower()
    assert channel.success_count == 0
    assert channel.last_success_at is None
    item.status = "QUEUED"
    item.error_message = None
    processed = process_outbound_queue(
        db_session,
        settings=settings,
    )
    assert processed["simulated"] == 1
    assert processed["accepted"] == 0
    assert item.status == "SIMULATED"
    assert item.attempt_count == 0
    assert channel.success_count == 0


def test_existing_mock_channel_fails_closed_outside_demo_mode(
    db_session,
    tmp_path: Path,
) -> None:
    _, tenant, channel = _tenant_and_channel(
        db_session,
        tmp_path,
        provider="MOCK",
    )
    production_settings = Settings(
        _env_file=None,
        demo_mode=False,
        credential_encryption_key=(
            "email-tests-use-a-dedicated-credential-encryption-key-2026"
        ),
        email_attachment_storage_path=str(tmp_path / "attachments"),
    )
    item = queue_email(
        db_session,
        to_email="recipient@example.test",
        subject="Must fail closed",
        body="Mock transport is not a production transport.",
        tenant_id=tenant.id,
        settings=production_settings,
    )
    assert item.status == "FAILED"
    assert item.sent_at is None
    assert item.provider_message_id is None
    assert "disabled outside demo mode" in (item.error_message or "")
    assert channel.success_count == 0


def test_inbound_email_creates_ticket_is_idempotent_and_threads_reply(
    db_session,
    tmp_path: Path,
) -> None:
    settings, _, channel = _tenant_and_channel(db_session, tmp_path)
    first = ingest_graph_message(
        db_session,
        channel=channel,
        message=_graph_message("message-1"),
        settings=settings,
    )
    db_session.flush()
    assert first is not None
    assert first.status == "PROCESSED"
    assert first.related_ticket_id
    ticket = db_session.get(Ticket, first.related_ticket_id)
    assert ticket is not None
    assert ticket.category == "MAIL"
    assert ticket.requester_email == "requester@example.test"

    replay = ingest_graph_message(
        db_session,
        channel=channel,
        message=_graph_message("message-1"),
        settings=settings,
    )
    assert replay is first
    assert (
        db_session.scalar(
            select(func.count(Ticket.id)).where(Ticket.tenant_id == channel.tenant_id)
        )
        == 1
    )

    conversation = db_session.get(EmailConversation, first.conversation_id)
    assert conversation is not None
    reply = ingest_graph_message(
        db_session,
        channel=channel,
        message=_graph_message(
            "message-2",
            subject=f"Re: Cannot connect to Wi-Fi [SBS:T:{conversation.thread_token}]",
            body="The problem still happens.",
            conversation_id="graph-conversation-1",
        ),
        settings=settings,
    )
    db_session.flush()
    assert reply is not None
    assert reply.related_ticket_id == ticket.id
    assert reply.ticket_comment_id
    comment = db_session.get(TicketComment, reply.ticket_comment_id)
    assert comment is not None
    assert comment.is_internal is False
    assert "still happens" in comment.body


def test_spoofed_thread_and_platform_loop_are_not_added_to_ticket(
    db_session,
    tmp_path: Path,
) -> None:
    settings, _, channel = _tenant_and_channel(db_session, tmp_path)
    first = ingest_graph_message(
        db_session,
        channel=channel,
        message=_graph_message("secure-thread-1"),
        settings=settings,
    )
    db_session.flush()
    assert first is not None
    conversation = db_session.get(EmailConversation, first.conversation_id)
    assert conversation is not None

    spoofed = ingest_graph_message(
        db_session,
        channel=channel,
        message=_graph_message(
            "secure-thread-2",
            sender="attacker@outside.test",
            subject=f"Re: ticket [SBS:T:{conversation.thread_token}]",
        ),
        settings=settings,
    )
    assert spoofed is not None
    assert spoofed.status == "QUARANTINED"
    assert spoofed.ticket_comment_id is None

    loop = ingest_graph_message(
        db_session,
        channel=channel,
        message=_graph_message(
            "secure-thread-3",
            headers=[{"name": "X-SBS-Loop-Token", "value": "email-loop-token"}],
        ),
        settings=settings,
    )
    assert loop is not None
    assert loop.status == "LOOP"
    assert loop.related_ticket_id is None


def test_inbound_attachments_are_quarantined_or_blocked(
    db_session,
    tmp_path: Path,
) -> None:
    settings, _, channel = _tenant_and_channel(db_session, tmp_path)
    pdf_payload = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    graph = _AttachmentGraph(
        [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": "attachment-safe",
                "name": "../../report.pdf",
                "contentType": "application/pdf",
                "size": len(pdf_payload),
                "contentBytes": base64.b64encode(pdf_payload).decode("ascii"),
                "isInline": False,
            },
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": "attachment-executable",
                "name": "payload.exe",
                "contentType": "application/octet-stream",
                "size": 4,
                "contentBytes": base64.b64encode(b"test").decode("ascii"),
                "isInline": False,
            },
        ]
    )
    inbound = ingest_graph_message(
        db_session,
        channel=channel,
        message=_graph_message("attachment-message", has_attachments=True),
        graph_client=graph,
        settings=settings,
    )
    db_session.flush()
    assert inbound is not None
    attachments = list(
        db_session.scalars(
            select(EmailAttachment)
            .where(EmailAttachment.inbound_message_id == inbound.id)
            .order_by(EmailAttachment.provider_attachment_id)
        ).all()
    )
    assert len(attachments) == 2
    executable = next(item for item in attachments if item.original_filename == "payload.exe")
    safe = next(item for item in attachments if item.original_filename.endswith("report.pdf"))
    assert executable.status == "BLOCKED"
    assert executable.storage_key is None
    assert safe.safe_filename == "report.pdf"
    assert safe.status == "QUARANTINED"
    assert safe.scan_status == "PENDING"
    assert safe.detected_content_type == "application/pdf"
    assert safe.security_findings_json == "[]"
    assert safe.sha256
    assert (Path(settings.email_attachment_storage_path) / (safe.storage_key or "")).is_file()


def test_attachment_inspection_blocks_disguised_executable_and_dlp_secret() -> None:
    executable = inspect_attachment_payload(
        b"MZ" + b"\x00" * 128,
        extension=".pdf",
        declared_content_type="application/pdf",
    )
    sensitive = inspect_attachment_payload(
        b"-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----",
        extension=".txt",
        declared_content_type="text/plain",
    )

    assert executable.blocked_reason
    assert "executable_content_signature" in executable.security_findings
    assert "content_mime_mismatch" in executable.security_findings
    assert sensitive.blocked_reason
    assert "dlp_private_key_material" in sensitive.security_findings


def test_attachment_inspection_blocks_zip_bomb_and_nested_archive() -> None:
    nested_buffer = BytesIO()
    with zipfile.ZipFile(nested_buffer, "w", zipfile.ZIP_DEFLATED) as nested:
        nested.writestr("payload.txt", "safe")
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("nested.zip", nested_buffer.getvalue())
        archive.writestr("high-ratio.txt", b"0" * 2_000_000)

    inspection = inspect_attachment_payload(
        archive_buffer.getvalue(),
        extension=".zip",
        declared_content_type="application/zip",
    )

    assert inspection.blocked_reason
    assert "nested_archive" in inspection.security_findings
    assert "archive_compression_ratio_exceeded" in inspection.security_findings


def test_attachment_inspection_strips_jpeg_exif_before_hashing() -> None:
    exif = b"Exif\x00\x00"
    jpeg = (
        b"\xff\xd8"
        + b"\xff\xe1"
        + (len(exif) + 2).to_bytes(2, "big")
        + exif
        + b"\xff\xda\x00\x02\xff\xd9"
    )

    inspection = inspect_attachment_payload(
        jpeg,
        extension=".jpg",
        declared_content_type="image/jpeg",
    )

    assert inspection.blocked_reason is None
    assert inspection.sanitization_applied is True
    assert "metadata_stripped" in inspection.security_findings
    assert b"Exif" not in inspection.payload


def test_attachment_release_and_signed_download_are_fail_closed(app, tmp_path: Path) -> None:
    from app.db.session import SessionLocal

    pdf_payload = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    with TestClient(app) as client, SessionLocal() as db:
        settings, _, channel = _tenant_and_channel(db, tmp_path)
        inbound = ingest_graph_message(
            db,
            channel=channel,
            message=_graph_message("signed-download", has_attachments=True),
            graph_client=_AttachmentGraph(
                [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "id": "signed-pdf",
                        "name": "evidence.pdf",
                        "contentType": "application/pdf",
                        "size": len(pdf_payload),
                        "contentBytes": base64.b64encode(pdf_payload).decode("ascii"),
                        "isInline": False,
                    }
                ]
            ),
            settings=settings,
        )
        assert inbound is not None
        db.commit()
        attachment = db.scalar(
            select(EmailAttachment).where(
                EmailAttachment.inbound_message_id == inbound.id
            )
        )
        assert attachment is not None
        attachment_id = attachment.id
        assert attachment.status == "QUARANTINED"

        token = _login(client, "root@sbs.local", "Root!2026")
        denied_release = client.post(
            f"/api/v1/email/attachments/{attachment_id}/decision",
            headers=_headers(token),
            json={"decision": "RELEASE", "reason": "No clean scanner result"},
        )
        assert denied_release.status_code == 409

        db.refresh(attachment)
        attachment.scan_status = "CLEAN"
        attachment.status = "STORED"
        attachment.blocked_reason = None
        db.commit()

        issued = client.post(
            f"/api/v1/email/attachments/{attachment_id}/download-token",
            headers=_headers(token),
        )
        assert issued.status_code == 200, issued.text
        signed_token = issued.json()["token"]
        assert issued.json()["ttl_seconds"] <= 300

        downloaded = client.get(
            f"/api/v1/email/attachments/{attachment_id}/download",
            params={"token": signed_token},
            headers=_headers(token),
        )
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == pdf_payload
        assert downloaded.headers["cache-control"] == "private, no-store, max-age=0"
        assert downloaded.headers["x-content-type-options"] == "nosniff"

        tampered = client.get(
            f"/api/v1/email/attachments/{attachment_id}/download",
            params={"token": signed_token[:-1] + ("A" if signed_token[-1] != "A" else "B")},
            headers=_headers(token),
        )
        assert tampered.status_code == 401

        db.expire_all()
        assert db.get(EmailAttachment, attachment_id).download_count == 1


def test_outbound_graph_queue_stops_at_accepted_until_delivery_signal(
    db_session,
    tmp_path: Path,
) -> None:
    settings, tenant, channel = _tenant_and_channel(db_session, tmp_path)
    item = queue_email(
        db_session,
        to_email="recipient@example.test",
        subject="Production queue",
        body="This must be accepted without claiming delivery.",
        tenant_id=tenant.id,
        idempotency_key="email-test-idempotency",
        settings=settings,
    )
    db_session.flush()
    assert item.status == "QUEUED"
    result = process_outbound_queue(
        db_session,
        settings=settings,
        graph_client_factory=_SuccessfulGraph,
    )
    assert result["accepted"] == 1
    assert item.status == "ACCEPTED"
    assert item.accepted_at is not None
    assert item.delivered_at is None
    assert item.provider_message_id == "graph-request-accepted"
    replay = queue_email(
        db_session,
        to_email="other@example.test",
        subject="Duplicate",
        body="Must return the original queue record.",
        tenant_id=tenant.id,
        idempotency_key="email-test-idempotency",
        settings=settings,
    )
    assert replay.id == item.id
    assert channel.success_count == 1


def test_webhook_notifications_are_deduplicated(db_session, tmp_path: Path) -> None:
    _, _, channel = _tenant_and_channel(db_session, tmp_path)
    notification = {
        "subscriptionId": "subscription-1",
        "changeType": "created",
        "resource": "users/service/messages/message-1",
        "resourceData": {"id": "message-1"},
    }
    assert (
        persist_graph_notifications(
            db_session,
            channel=channel,
            notifications=[notification],
        )
        == 1
    )
    db_session.flush()
    assert (
        persist_graph_notifications(
            db_session,
            channel=channel,
            notifications=[notification],
        )
        == 0
    )


def test_credential_ciphertext_is_bound_to_tenant_and_purpose(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    ciphertext = encrypt_credential(
        "very-sensitive-value",
        purpose="email-channel:test:client-secret",
        tenant_id="tenant-a",
        settings=settings,
    )
    assert "very-sensitive-value" not in ciphertext
    assert (
        decrypt_credential(
            ciphertext,
            purpose="email-channel:test:client-secret",
            tenant_id="tenant-a",
            settings=settings,
        )
        == "very-sensitive-value"
    )
    try:
        decrypt_credential(
            ciphertext,
            purpose="email-channel:test:client-secret",
            tenant_id="tenant-b",
            settings=settings,
        )
    except Exception:
        pass
    else:
        raise AssertionError("Ciphertext must not decrypt under another tenant")
