from __future__ import annotations

import json
import hashlib
import hmac
import struct
import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from app.models.audit_chain_head import AuditChainHead
from app.models.audit_log import AuditLog
from app.models.user import User


GLOBAL_AUDIT_SCOPE = "global"
_LOCAL_AUDIT_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_AUDIT_LOCKS_GUARD = threading.Lock()
_SESSION_AUDIT_LOCKS_KEY = "sbs_audit_chain_locks"


@event.listens_for(Session, "after_transaction_end")
def _release_local_audit_locks(db: Session, transaction) -> None:
    """Release process-local locks only after the outer transaction ends."""
    if transaction.parent is not None:
        return
    held = db.info.pop(_SESSION_AUDIT_LOCKS_KEY, {})
    for lock in held.values():
        lock.release()


def _normalized_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def compute_audit_event_hash(
    *,
    audit_id: str,
    chain_scope: str,
    sequence: int,
    previous_hash: str | None,
    actor_email: str,
    action: str,
    entity_type: str,
    entity_id: str | None,
    ip_address: str | None,
    user_agent: str | None,
    metadata_json: str | None,
    created_at: datetime,
) -> str:
    canonical = json.dumps(
        {
            "id": audit_id,
            "chain_scope": chain_scope,
            "sequence": sequence,
            "previous_hash": previous_hash,
            "actor_email": actor_email,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "metadata": metadata_json,
            "created_at": _normalized_timestamp(created_at),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _lock_chain_scope(db: Session, chain_scope: str) -> None:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        lock_key = struct.unpack(
            ">q",
            hashlib.sha256(chain_scope.encode("utf-8")).digest()[:8],
        )[0]
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
        return

    # SQLite has no row-level or advisory locks. Keep one process-local lock
    # per chain scope until commit/rollback so concurrent local requests cannot
    # allocate the same sequence number. Production PostgreSQL remains
    # protected by the transaction-scoped advisory lock above.
    held = db.info.setdefault(_SESSION_AUDIT_LOCKS_KEY, {})
    if chain_scope in held:
        return
    with _LOCAL_AUDIT_LOCKS_GUARD:
        scope_lock = _LOCAL_AUDIT_LOCKS.setdefault(chain_scope, threading.Lock())
    scope_lock.acquire()
    held[chain_scope] = scope_lock


def _chain_head(db: Session, chain_scope: str) -> AuditChainHead | None:
    pending = next(
        (
            item
            for item in db.new
            if isinstance(item, AuditChainHead) and item.scope == chain_scope
        ),
        None,
    )
    if pending is not None:
        return pending
    return db.get(AuditChainHead, chain_scope, with_for_update=True)


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
    stable_tenant_id = tenant_id if tenant_id is not None else (
        actor_user.tenant_id if actor_user is not None else None
    )
    chain_scope = stable_tenant_id or GLOBAL_AUDIT_SCOPE
    _lock_chain_scope(db, chain_scope)
    head = _chain_head(db, chain_scope)
    previous_hash = head.last_event_hash if head is not None else None
    sequence = (head.event_count if head is not None else 0) + 1
    audit_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    metadata_json = json.dumps(
        metadata or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    stable_actor_email = actor_email or (
        actor_user.email if actor_user is not None else "unknown@sbs.local"
    )
    event_hash = compute_audit_event_hash(
        audit_id=audit_id,
        chain_scope=chain_scope,
        sequence=sequence,
        previous_hash=previous_hash,
        actor_email=stable_actor_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=metadata_json,
        created_at=created_at,
    )
    payload = AuditLog(
        id=audit_id,
        tenant_id=stable_tenant_id,
        actor_user_id=actor_user.id if actor_user is not None else None,
        actor_email=stable_actor_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_json=metadata_json,
        chain_scope=chain_scope,
        sequence=sequence,
        previous_hash=previous_hash,
        event_hash=event_hash,
        created_at=created_at,
    )
    db.add(payload)
    if head is None:
        db.add(
            AuditChainHead(
                scope=chain_scope,
                last_event_hash=event_hash,
                event_count=sequence,
                updated_at=created_at,
            )
        )
    else:
        head.last_event_hash = event_hash
        head.event_count = sequence
        head.updated_at = created_at
    return payload


def verify_audit_chains(db: Session, *, scopes: set[str] | None = None) -> dict[str, object]:
    statement = select(AuditLog).order_by(AuditLog.chain_scope.asc(), AuditLog.sequence.asc())
    if scopes:
        statement = statement.where(AuditLog.chain_scope.in_(scopes))
    rows = db.scalars(statement).all()
    failures: list[dict[str, object]] = []
    expected_by_scope: dict[str, tuple[int, str | None]] = {}
    for row in rows:
        expected_sequence, expected_previous = expected_by_scope.get(row.chain_scope, (1, None))
        calculated = compute_audit_event_hash(
            audit_id=row.id,
            chain_scope=row.chain_scope,
            sequence=row.sequence,
            previous_hash=row.previous_hash,
            actor_email=row.actor_email,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            ip_address=row.ip_address,
            user_agent=row.user_agent,
            metadata_json=row.metadata_json,
            created_at=row.created_at,
        )
        if (
            row.sequence != expected_sequence
            or row.previous_hash != expected_previous
            or not secrets_compare(row.event_hash, calculated)
        ):
            failures.append(
                {
                    "scope": row.chain_scope,
                    "sequence": row.sequence,
                    "audit_id": row.id,
                }
            )
        expected_by_scope[row.chain_scope] = (row.sequence + 1, row.event_hash)

    head_statement = select(AuditChainHead)
    if scopes:
        head_statement = head_statement.where(AuditChainHead.scope.in_(scopes))
    heads = {item.scope: item for item in db.scalars(head_statement).all()}
    for scope, (next_sequence, last_hash) in expected_by_scope.items():
        head = heads.get(scope)
        if head is None or head.event_count != next_sequence - 1 or not secrets_compare(
            head.last_event_hash, last_hash or ""
        ):
            failures.append({"scope": scope, "sequence": next_sequence - 1, "audit_id": None})
    for scope, head in heads.items():
        if scope not in expected_by_scope:
            failures.append(
                {"scope": scope, "sequence": head.event_count, "audit_id": None}
            )
    return {
        "valid": not failures,
        "events_checked": len(rows),
        "chains_checked": len(expected_by_scope),
        "failures": failures[:100],
    }


def secrets_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


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
    failed_actions = ["login_failed", "login_mfa_failed"]
    failed = int(
        db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.action.in_(failed_actions),
                AuditLog.created_at >= day_start,
            )
        )
        or 0
    )
    success = int(db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "login_success", AuditLog.created_at >= day_start)) or 0)
    recent = db.scalars(
        select(AuditLog)
        .where(
            (AuditLog.action.like("security.%"))
            | (AuditLog.action.in_(["login_mfa_failed", "mfa_admin_reset", "mfa_disabled"]))
        )
        .order_by(AuditLog.created_at.desc())
        .limit(10)
    ).all()
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
