from sqlalchemy import delete, select

from app.models.audit_log import AuditLog
from app.services.audit import log_audit, verify_audit_chains


def test_audit_hash_chain_detects_tampering(db_session) -> None:
    first = log_audit(
        db_session,
        action="security.policy.updated",
        entity_type="policy",
        entity_id="policy-1",
        actor_email="security@example.com",
        tenant_id="tenant-a",
        metadata={"version": 1},
    )
    second = log_audit(
        db_session,
        action="security.policy.activated",
        entity_type="policy",
        entity_id="policy-1",
        actor_email="security@example.com",
        tenant_id="tenant-a",
        metadata={"version": 1},
    )
    db_session.commit()

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_hash == first.event_hash
    assert verify_audit_chains(db_session, scopes={"tenant-a"})["valid"] is True

    stored = db_session.scalar(select(AuditLog).where(AuditLog.id == first.id))
    assert stored is not None
    stored.metadata_json = '{"version":999}'
    db_session.commit()

    verification = verify_audit_chains(db_session, scopes={"tenant-a"})
    assert verification["valid"] is False
    assert verification["failures"][0]["audit_id"] == first.id


def test_audit_hash_chain_detects_deleted_chain_events(db_session) -> None:
    log_audit(
        db_session,
        action="security.policy.updated",
        entity_type="policy",
        entity_id="policy-2",
        actor_email="security@example.com",
        tenant_id="tenant-b",
    )
    db_session.commit()

    db_session.execute(delete(AuditLog).where(AuditLog.chain_scope == "tenant-b"))
    db_session.commit()

    verification = verify_audit_chains(db_session, scopes={"tenant-b"})
    assert verification["valid"] is False
    assert verification["failures"] == [
        {"scope": "tenant-b", "sequence": 1, "audit_id": None}
    ]
