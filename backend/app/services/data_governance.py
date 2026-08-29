from __future__ import annotations

import hashlib
from io import BytesIO
import json
from datetime import UTC, datetime, timedelta
from typing import Any
import zipfile

from sqlalchemy import delete, func, inspect, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.models.ai_retrieval import AiRetrievalDocument, AiRetrievalQueryLog
from app.models.ai_runtime_controls import AiUsageLedger
from app.models.audit_log import AuditLog
from app.models.data_governance import (
    DataLegalHold,
    DataRetentionPolicy,
    RETENTION_CATEGORIES,
)
from app.models.email_channel import EmailAttachment, EmailInboundMessage
from app.models.email_message_log import EmailMessageLog
from app.models.job_run import JobRun
from app.models.notification import Notification
from app.models.report_snapshot import ReportSnapshot
from app.models.service_request import RequestActivity, ServiceRequest
from app.models.tenant import Tenant
from app.models.ticket import Ticket
from app.models.ticket_comment import TicketComment
from app.services.email_attachments import delete_attachment_content


GLOBAL_MINIMUM_RETENTION_DAYS: dict[str, int] = {
    "TICKETS": 365,
    "SERVICE_REQUESTS": 365,
    "COMMENTS": 365,
    "NOTIFICATIONS": 90,
    "LOGIN_EVENTS": 365,
    "AUDIT": 2_555,
    "EMAIL": 365,
    "ATTACHMENTS": 365,
    "AI_CONVERSATIONS": 180,
    "AI_PROMPTS_RESPONSES": 365,
    "VECTOR_EMBEDDINGS": 90,
    "EXPORTS": 90,
    "BACKGROUND_JOBS": 180,
    "DEAD_LETTER": 365,
}

LOGIN_ACTIONS = (
    "login_success",
    "login_failed",
    "login_mfa_challenge",
    "login_mfa_failed",
    "oidc_login_success",
    "oidc_login_failed",
)
TERMINAL_REQUEST_STATUSES = ("COMPLETED", "CANCELLED", "REJECTED", "CLOSED")
TERMINAL_JOB_STATUSES = ("success", "failed", "cancelled")


class GovernanceBlockedExternal(RuntimeError):
    """A safe local workflow is ready but needs an external compliance service."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda item: as_utc(item).isoformat()
        if isinstance(item, datetime)
        else str(item),
    )


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _global_policy(db: Session, category: str) -> DataRetentionPolicy | None:
    return db.scalar(
        select(DataRetentionPolicy).where(
            DataRetentionPolicy.scope_key == "GLOBAL",
            DataRetentionPolicy.category == category,
            DataRetentionPolicy.is_enabled.is_(True),
        )
    )


def effective_policy(
    db: Session,
    *,
    tenant_id: str,
    category: str,
) -> dict[str, Any]:
    if category not in RETENTION_CATEGORIES:
        raise ValueError("Unsupported retention category")
    global_item = _global_policy(db, category)
    minimum_days = max(
        GLOBAL_MINIMUM_RETENTION_DAYS[category],
        global_item.retention_days if global_item else 0,
    )
    tenant_item = db.scalar(
        select(DataRetentionPolicy).where(
            DataRetentionPolicy.scope_key == f"TENANT:{tenant_id}",
            DataRetentionPolicy.category == category,
            DataRetentionPolicy.is_enabled.is_(True),
        )
    )
    requested_days = tenant_item.retention_days if tenant_item else minimum_days
    return {
        "category": category,
        "global_minimum_days": minimum_days,
        "tenant_requested_days": requested_days,
        "effective_retention_days": max(minimum_days, requested_days),
        "archive_before_delete": (
            tenant_item.archive_before_delete if tenant_item else True
        ),
        "anonymize_before_delete": (
            tenant_item.anonymize_before_delete if tenant_item else True
        ),
        "tenant_revision": tenant_item.revision if tenant_item else 0,
        "source": "TENANT" if tenant_item else "GLOBAL_DEFAULT",
    }


def active_holds(
    db: Session,
    *,
    tenant_id: str,
    category: str | None = None,
) -> list[DataLegalHold]:
    now = utcnow()
    statement = select(DataLegalHold).where(
        DataLegalHold.tenant_id == tenant_id,
        DataLegalHold.status == "ACTIVE",
        (DataLegalHold.expires_at.is_(None) | (DataLegalHold.expires_at > now)),
    )
    if category:
        statement = statement.where(
            (DataLegalHold.scope_type == "TENANT")
            | (DataLegalHold.category == category)
        )
    return list(db.scalars(statement.order_by(DataLegalHold.created_at)).all())


def _count(db: Session, statement: Any) -> int:
    return int(db.scalar(statement) or 0)


def category_preview(
    db: Session,
    *,
    tenant_id: str,
    category: str,
    now: datetime | None = None,
    cutoff_override: datetime | None = None,
) -> dict[str, Any]:
    policy = effective_policy(db, tenant_id=tenant_id, category=category)
    cutoff = as_utc(cutoff_override) if cutoff_override else (
        (now or utcnow())
        - timedelta(days=int(policy["effective_retention_days"]))
    )
    holds = active_holds(db, tenant_id=tenant_id, category=category)
    counts: dict[str, int]
    operation = "DELETE"
    if category == "TICKETS":
        counts = {
            "tickets": _count(
                db,
                select(func.count(Ticket.id)).where(
                    Ticket.tenant_id == tenant_id,
                    Ticket.status == "CLOSED",
                    Ticket.closed_at.is_not(None),
                    Ticket.closed_at < cutoff,
                ),
            )
        }
        operation = "ANONYMIZE"
    elif category == "SERVICE_REQUESTS":
        counts = {
            "service_requests": _count(
                db,
                select(func.count(ServiceRequest.id)).where(
                    ServiceRequest.tenant_id == tenant_id,
                    ServiceRequest.status.in_(TERMINAL_REQUEST_STATUSES),
                    ServiceRequest.updated_at < cutoff,
                ),
            )
        }
        operation = "ANONYMIZE"
    elif category == "COMMENTS":
        counts = {
            "ticket_comments": _count(
                db,
                select(func.count(TicketComment.id))
                .join(Ticket, Ticket.id == TicketComment.ticket_id)
                .where(
                    Ticket.tenant_id == tenant_id,
                    TicketComment.created_at < cutoff,
                ),
            )
        }
        operation = "ANONYMIZE"
    elif category == "NOTIFICATIONS":
        counts = {
            "notifications": _count(
                db,
                select(func.count(Notification.id)).where(
                    Notification.tenant_id == tenant_id,
                    Notification.created_at < cutoff,
                ),
            )
        }
    elif category in {"LOGIN_EVENTS", "AUDIT"}:
        login_filter = AuditLog.action.in_(LOGIN_ACTIONS)
        action_filter = login_filter if category == "LOGIN_EVENTS" else ~login_filter
        counts = {
            "audit_logs": _count(
                db,
                select(func.count(AuditLog.id)).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.created_at < cutoff,
                    action_filter,
                ),
            )
        }
        operation = "WORM_ARCHIVE_REQUIRED"
    elif category == "EMAIL":
        counts = {
            "email_inbound_messages": _count(
                db,
                select(func.count(EmailInboundMessage.id)).where(
                    EmailInboundMessage.tenant_id == tenant_id,
                    EmailInboundMessage.created_at < cutoff,
                ),
            ),
            "email_message_logs": _count(
                db,
                select(func.count(EmailMessageLog.id)).where(
                    EmailMessageLog.tenant_id == tenant_id,
                    EmailMessageLog.created_at < cutoff,
                ),
            ),
        }
        operation = "ANONYMIZE"
    elif category == "ATTACHMENTS":
        counts = {
            "email_attachments": _count(
                db,
                select(func.count(EmailAttachment.id)).where(
                    EmailAttachment.tenant_id == tenant_id,
                    EmailAttachment.created_at < cutoff,
                    EmailAttachment.storage_key.is_not(None),
                ),
            )
        }
    elif category == "AI_CONVERSATIONS":
        counts = {
            "ai_retrieval_query_logs": _count(
                db,
                select(func.count(AiRetrievalQueryLog.id)).where(
                    AiRetrievalQueryLog.tenant_id == tenant_id,
                    AiRetrievalQueryLog.created_at < cutoff,
                ),
            )
        }
    elif category == "AI_PROMPTS_RESPONSES":
        counts = {
            "ai_usage_ledger": _count(
                db,
                select(func.count(AiUsageLedger.id)).where(
                    AiUsageLedger.tenant_id == tenant_id,
                    AiUsageLedger.created_at < cutoff,
                ),
            )
        }
    elif category == "VECTOR_EMBEDDINGS":
        counts = {
            "ai_retrieval_documents": _count(
                db,
                select(func.count(AiRetrievalDocument.id)).where(
                    AiRetrievalDocument.tenant_id == tenant_id,
                    AiRetrievalDocument.status == "DELETED",
                    AiRetrievalDocument.deleted_at.is_not(None),
                    AiRetrievalDocument.deleted_at < cutoff,
                ),
            )
        }
    elif category == "EXPORTS":
        counts = {
            "report_snapshots": _count(
                db,
                select(func.count(ReportSnapshot.id)).where(
                    ReportSnapshot.tenant_id == tenant_id,
                    ReportSnapshot.created_at < cutoff,
                ),
            )
        }
    elif category == "BACKGROUND_JOBS":
        counts = {
            "job_runs": _count(
                db,
                select(func.count(JobRun.id)).where(
                    JobRun.tenant_id == tenant_id,
                    JobRun.status.in_(TERMINAL_JOB_STATUSES),
                    JobRun.updated_at < cutoff,
                ),
            )
        }
    elif category == "DEAD_LETTER":
        counts = {
            "job_runs": _count(
                db,
                select(func.count(JobRun.id)).where(
                    JobRun.tenant_id == tenant_id,
                    JobRun.status == "dead_letter",
                    JobRun.updated_at < cutoff,
                ),
            )
        }
    else:  # pragma: no cover - guarded by effective_policy
        raise ValueError("Unsupported retention category")

    preview = {
        "tenant_id": tenant_id,
        "category": category,
        "cutoff_at": cutoff,
        "operation": operation,
        "counts": counts,
        "estimated_rows": sum(counts.values()),
        "active_holds": [
            {
                "id": item.id,
                "name": item.name,
                "scope_type": item.scope_type,
                "category": item.category,
                "expires_at": item.expires_at,
            }
            for item in holds
        ],
        "blocked_by_legal_hold": bool(holds),
        "policy": policy,
    }
    preview["plan_sha256"] = sha256_json(preview)
    return preview


def tenant_deletion_preview(db: Session, *, tenant_id: str) -> dict[str, Any]:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("Tenant not found")
    counts: dict[str, int] = {}
    # Only direct tenant-scoped tables are counted here. Child rows are removed
    # through declared foreign-key cascades and are still covered by the schema
    # manifest in the export/evidence hash.
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        if (
            table.name.startswith("data_deletion_")
            or table.name in {"audit_logs", "data_legal_holds"}
            or "tenant_id" not in table.c
        ):
            continue
        counts[table.name] = _count(
            db,
            select(func.count()).select_from(table).where(
                table.c.tenant_id == tenant_id
            ),
        )
    holds = active_holds(db, tenant_id=tenant_id)
    preview = {
        "tenant_id": tenant_id,
        "tenant_name": tenant.name,
        "tenant_slug": tenant.slug,
        "operation": "TENANT_DELETE_CASCADE",
        "counts": counts,
        "estimated_rows": sum(counts.values()),
        "active_holds": [item.id for item in holds],
        "blocked_by_legal_hold": bool(holds),
        "schema_table_count": len(inspect(db.get_bind()).get_table_names()),
    }
    preview["plan_sha256"] = sha256_json(preview)
    return preview


_SECRET_COLUMN_MARKERS = (
    "password",
    "secret",
    "encrypted",
    "credential",
    "token_hash",
    "recovery_code",
    "totp",
)


def build_tenant_export(
    db: Session,
    *,
    tenant_id: str,
) -> tuple[bytes, dict[str, Any]]:
    """Build a secret-free relational tenant export with an integrity manifest."""

    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("Tenant not found")
    tables = Base.metadata.tables
    rows_by_table: dict[str, dict[tuple[object, ...], dict[str, object]]] = {}

    def add_rows(table_name: str, rows: list[dict[str, object]]) -> bool:
        table = tables[table_name]
        primary_keys = list(table.primary_key.columns)
        bucket = rows_by_table.setdefault(table_name, {})
        changed = False
        for row in rows:
            key = tuple(row[column.name] for column in primary_keys)
            if key not in bucket:
                bucket[key] = row
                changed = True
        return changed

    add_rows(
        "tenants",
        [dict(db.execute(select(tables["tenants"]).where(
            tables["tenants"].c.id == tenant_id
        )).mappings().one())],
    )
    for table in tables.values():
        if table.name == "tenants" or "tenant_id" not in table.c:
            continue
        rows = [
            dict(row)
            for row in db.execute(
                select(table).where(table.c.tenant_id == tenant_id)
            ).mappings()
        ]
        if rows:
            add_rows(table.name, rows)

    # Follow child foreign keys so comments, history, chunks, and other rows
    # without their own tenant_id remain part of the export.
    for _ in range(len(tables)):
        changed = False
        for table in tables.values():
            predicates = []
            for foreign_key in table.foreign_keys:
                parent_name = foreign_key.column.table.name
                parent_rows = rows_by_table.get(parent_name, {})
                if not parent_rows:
                    continue
                parent_column = foreign_key.column.name
                values = {
                    row[parent_column]
                    for row in parent_rows.values()
                    if row.get(parent_column) is not None
                }
                if values:
                    predicates.append(foreign_key.parent.in_(values))
            if not predicates:
                continue
            predicate = predicates[0]
            for extra in predicates[1:]:
                predicate = predicate | extra
            rows = [
                dict(row)
                for row in db.execute(select(table).where(predicate)).mappings()
            ]
            if rows:
                changed = add_rows(table.name, rows) or changed
        if not changed:
            break

    archive = BytesIO()
    table_manifest: dict[str, dict[str, object]] = {}
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as bundle:
        for table_name in sorted(rows_by_table):
            rows = rows_by_table[table_name]
            if not rows:
                continue
            table = tables[table_name]
            omitted_columns = sorted(
                column.name
                for column in table.columns
                if any(marker in column.name.lower() for marker in _SECRET_COLUMN_MARKERS)
            )
            lines: list[str] = []
            for row in rows.values():
                safe_row = {
                    key: value
                    for key, value in row.items()
                    if key not in omitted_columns
                }
                lines.append(canonical_json(safe_row))
            payload = ("\n".join(lines) + "\n").encode("utf-8")
            bundle.writestr(f"tables/{table_name}.jsonl", payload)
            table_manifest[table_name] = {
                "rows": len(lines),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "omitted_secret_columns": omitted_columns,
            }
        manifest = {
            "format": "sbs-ai-itsm-tenant-export-v1",
            "tenant_id": tenant_id,
            "tenant_slug": tenant.slug,
            "created_at": utcnow(),
            "table_count": len(table_manifest),
            "row_count": sum(int(item["rows"]) for item in table_manifest.values()),
            "tables": table_manifest,
            "secrets_included": False,
        }
        manifest["manifest_sha256"] = sha256_json(manifest)
        bundle.writestr("manifest.json", canonical_json(manifest).encode("utf-8"))
    payload = archive.getvalue()
    manifest["archive_sha256"] = hashlib.sha256(payload).hexdigest()
    return payload, manifest


def _ids_digest(ids: list[str]) -> str:
    digest = hashlib.sha256()
    for identifier in sorted(ids):
        digest.update(identifier.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def execute_category_retention(
    db: Session,
    *,
    tenant_id: str,
    category: str,
    cutoff: datetime,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if active_holds(db, tenant_id=tenant_id, category=category):
        raise ValueError("Deletion is blocked by an active legal hold")
    if category in {"LOGIN_EVENTS", "AUDIT"}:
        raise GovernanceBlockedExternal(
            "Immutable audit-chain retirement requires an accepted external WORM "
            "archive target and archive receipt before local chain segments may be removed"
        )

    identifiers: list[str] = []
    affected = 0
    action = "DELETED"
    if category == "TICKETS":
        identifiers = list(
            db.scalars(
                select(Ticket.id).where(
                    Ticket.tenant_id == tenant_id,
                    Ticket.status == "CLOSED",
                    Ticket.closed_at.is_not(None),
                    Ticket.closed_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(
                    update(Ticket)
                    .where(Ticket.id.in_(identifiers))
                    .values(
                        requester_id=None,
                        requester_name="Anonymized requester",
                        requester_email="anonymized@invalid.local",
                        department="Anonymized",
                        location="Anonymized",
                        title="Retained ticket",
                        description="Personal data removed by approved retention policy.",
                        reopen_reason=None,
                    )
                ).rowcount
                or 0
            )
        action = "ANONYMIZED"
    elif category == "SERVICE_REQUESTS":
        identifiers = list(
            db.scalars(
                select(ServiceRequest.id).where(
                    ServiceRequest.tenant_id == tenant_id,
                    ServiceRequest.status.in_(TERMINAL_REQUEST_STATUSES),
                    ServiceRequest.updated_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(
                    update(ServiceRequest)
                    .where(ServiceRequest.id.in_(identifiers))
                    .values(
                        requester_id=None,
                        requester_name="Anonymized requester",
                        requester_email="anonymized@invalid.local",
                        title="Retained service request",
                        description="Personal data removed by approved retention policy.",
                        requester_department=None,
                        requester_location=None,
                        cost_center=None,
                    )
                ).rowcount
                or 0
            )
            db.execute(
                update(RequestActivity)
                .where(RequestActivity.request_id.in_(identifiers))
                .values(
                    actor_user_id=None,
                    actor_name="Anonymized actor",
                    actor_email=None,
                    message="Activity retained; personal data removed.",
                    old_value_json=None,
                    new_value_json=None,
                )
            )
        action = "ANONYMIZED"
    elif category == "COMMENTS":
        identifiers = list(
            db.scalars(
                select(TicketComment.id)
                .join(Ticket, Ticket.id == TicketComment.ticket_id)
                .where(
                    Ticket.tenant_id == tenant_id,
                    TicketComment.created_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(
                    update(TicketComment)
                    .where(TicketComment.id.in_(identifiers))
                    .values(
                        author_id=None,
                        author_name="Anonymized actor",
                        body="Comment content removed by approved retention policy.",
                    )
                ).rowcount
                or 0
            )
        action = "ANONYMIZED"
    elif category == "NOTIFICATIONS":
        identifiers = list(
            db.scalars(
                select(Notification.id).where(
                    Notification.tenant_id == tenant_id,
                    Notification.created_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(delete(Notification).where(Notification.id.in_(identifiers))).rowcount
                or 0
            )
    elif category == "EMAIL":
        inbound_ids = list(
            db.scalars(
                select(EmailInboundMessage.id).where(
                    EmailInboundMessage.tenant_id == tenant_id,
                    EmailInboundMessage.created_at < cutoff,
                )
            ).all()
        )
        outbound_ids = list(
            db.scalars(
                select(EmailMessageLog.id).where(
                    EmailMessageLog.tenant_id == tenant_id,
                    EmailMessageLog.created_at < cutoff,
                )
            ).all()
        )
        identifiers = [f"in:{item}" for item in inbound_ids] + [
            f"out:{item}" for item in outbound_ids
        ]
        if inbound_ids:
            affected += int(
                db.execute(
                    update(EmailInboundMessage)
                    .where(EmailInboundMessage.id.in_(inbound_ids))
                    .values(
                        from_email="anonymized@invalid.local",
                        from_name=None,
                        recipients_json=[],
                        subject="Retained email",
                        body_text="Personal data removed by approved retention policy.",
                        body_html_sanitized=None,
                        headers_json={},
                        authentication_results=None,
                    )
                ).rowcount
                or 0
            )
        if outbound_ids:
            affected += int(
                db.execute(
                    update(EmailMessageLog)
                    .where(EmailMessageLog.id.in_(outbound_ids))
                    .values(
                        from_email=None,
                        from_name=None,
                        to_email="anonymized@invalid.local",
                        to_name=None,
                        subject="Retained email",
                        body="Personal data removed by approved retention policy.",
                        payload_json=None,
                        metadata_json=None,
                        headers_json=None,
                        error_message=None,
                    )
                ).rowcount
                or 0
            )
        action = "ANONYMIZED"
    elif category == "ATTACHMENTS":
        runtime = settings or get_settings()
        items = list(
            db.scalars(
                select(EmailAttachment).where(
                    EmailAttachment.tenant_id == tenant_id,
                    EmailAttachment.created_at < cutoff,
                    EmailAttachment.storage_key.is_not(None),
                )
            ).all()
        )
        identifiers = [item.id for item in items]
        for item in items:
            delete_attachment_content(item, settings=runtime)
            item.original_filename = "retention-purged.bin"
            item.safe_filename = "retention-purged.bin"
            item.content_id = None
            item.status = "BLOCKED"
            item.scan_status = "NOT_REQUIRED"
            item.blocked_reason = "Content deleted by approved retention policy"
            affected += 1
    elif category == "AI_CONVERSATIONS":
        identifiers = list(
            db.scalars(
                select(AiRetrievalQueryLog.id).where(
                    AiRetrievalQueryLog.tenant_id == tenant_id,
                    AiRetrievalQueryLog.created_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(
                    delete(AiRetrievalQueryLog).where(
                        AiRetrievalQueryLog.id.in_(identifiers)
                    )
                ).rowcount
                or 0
            )
    elif category == "AI_PROMPTS_RESPONSES":
        identifiers = list(
            db.scalars(
                select(AiUsageLedger.id).where(
                    AiUsageLedger.tenant_id == tenant_id,
                    AiUsageLedger.created_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(
                    delete(AiUsageLedger).where(AiUsageLedger.id.in_(identifiers))
                ).rowcount
                or 0
            )
    elif category == "VECTOR_EMBEDDINGS":
        identifiers = list(
            db.scalars(
                select(AiRetrievalDocument.id).where(
                    AiRetrievalDocument.tenant_id == tenant_id,
                    AiRetrievalDocument.status == "DELETED",
                    AiRetrievalDocument.deleted_at.is_not(None),
                    AiRetrievalDocument.deleted_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(
                    delete(AiRetrievalDocument).where(
                        AiRetrievalDocument.id.in_(identifiers)
                    )
                ).rowcount
                or 0
            )
    elif category == "EXPORTS":
        identifiers = list(
            db.scalars(
                select(ReportSnapshot.id).where(
                    ReportSnapshot.tenant_id == tenant_id,
                    ReportSnapshot.created_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(
                    delete(ReportSnapshot).where(ReportSnapshot.id.in_(identifiers))
                ).rowcount
                or 0
            )
    elif category in {"BACKGROUND_JOBS", "DEAD_LETTER"}:
        statuses = TERMINAL_JOB_STATUSES if category == "BACKGROUND_JOBS" else ("dead_letter",)
        identifiers = list(
            db.scalars(
                select(JobRun.id).where(
                    JobRun.tenant_id == tenant_id,
                    JobRun.status.in_(statuses),
                    JobRun.updated_at < cutoff,
                )
            ).all()
        )
        if identifiers:
            affected = int(
                db.execute(delete(JobRun).where(JobRun.id.in_(identifiers))).rowcount
                or 0
            )
    else:
        raise ValueError("Unsupported retention category")

    return {
        "category": category,
        "cutoff_at": cutoff,
        "action": action,
        "affected_rows": affected,
        "eligible_identifiers_sha256": _ids_digest(identifiers),
    }


def execute_tenant_deletion(
    db: Session,
    *,
    tenant_id: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if active_holds(db, tenant_id=tenant_id):
        raise ValueError("Tenant deletion is blocked by an active legal hold")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError("Tenant not found")
    runtime = settings or get_settings()
    attachments = list(
        db.scalars(
            select(EmailAttachment).where(
                EmailAttachment.tenant_id == tenant_id,
                EmailAttachment.storage_key.is_not(None),
            )
        ).all()
    )
    removed_files = sum(
        int(delete_attachment_content(item, settings=runtime))
        for item in attachments
    )
    before = tenant_deletion_preview(db, tenant_id=tenant_id)
    db.delete(tenant)
    db.flush()
    return {
        "tenant_id": tenant_id,
        "action": "TENANT_DELETED",
        "direct_rows_before": before["estimated_rows"],
        "attachment_files_removed": removed_files,
        "schema_manifest_sha256": sha256_json(before["counts"]),
    }
