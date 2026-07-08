from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def log_audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    actor_user: User | None = None,
    actor_email: str | None = None,
    tenant_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, object] | None = None,
) -> AuditLog:
    payload = AuditLog(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id if tenant_id is not None else (actor_user.tenant_id if actor_user is not None else None),
        actor_user_id=actor_user.id if actor_user is not None else None,
        actor_email=actor_email or (actor_user.email if actor_user is not None else "unknown@sbs.local"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        created_at=datetime.now(UTC),
    )
    db.add(payload)
    return payload


def parse_metadata(value: str | None) -> dict[str, object]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def summarize_security(db: Session) -> dict[str, object]:
    now = datetime.now(UTC)
    day_start = now - timedelta(days=1)
    failed = int(db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "login_failed", AuditLog.created_at >= day_start)) or 0)
    success = int(db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "login_success", AuditLog.created_at >= day_start)) or 0)
    recent = db.scalars(select(AuditLog).where(AuditLog.action.like("security.%")).order_by(AuditLog.created_at.desc()).limit(10)).all()
    active_users = int(db.scalar(select(func.count(User.id)).where(User.is_active == True)) or 0)  # noqa: E712
    risk_level = "low"
    if failed >= 10:
        risk_level = "high"
    elif failed >= 4:
        risk_level = "medium"
    return {
        "failed_logins_24h": failed,
        "success_logins_24h": success,
        "active_users": active_users,
        "risk_level": risk_level,
        "recent_security_events": [
            {
                "id": item.id,
                "action": item.action,
                "actor_email": item.actor_email,
                "created_at": item.created_at,
                "metadata": parse_metadata(item.metadata_json),
            }
            for item in recent
        ],
    }
