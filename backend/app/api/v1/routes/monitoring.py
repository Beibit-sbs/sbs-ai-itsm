from __future__ import annotations

import hashlib
import secrets
import struct
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import metrics_registry
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.services.audit import log_audit


router = APIRouter(prefix="/monitoring")


class AlertmanagerAlert(BaseModel):
    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str = ""
    endsAt: str = ""
    generatorURL: str = ""
    fingerprint: str = Field(min_length=1, max_length=128)


class AlertmanagerWebhook(BaseModel):
    version: str = "4"
    groupKey: str = ""
    status: Literal["firing", "resolved"]
    receiver: str = ""
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str = ""
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=100)


def _require_monitoring_token(authorization: str | None) -> None:
    settings = get_settings()
    expected = settings.alertmanager_webhook_token or ""
    provided = ""
    if authorization and authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ").strip()
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid monitoring token",
        )


def _bounded_mapping(values: dict[str, str], *, limit: int) -> dict[str, str]:
    return {
        str(key)[:120]: str(value)[:2000]
        for key, value in list(values.items())[:limit]
    }


def _alert_event_id(alert: AlertmanagerAlert) -> str:
    value = "\x00".join((alert.fingerprint, alert.status, alert.startsAt))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lock_alert_event(db: Session, event_id: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    lock_key = struct.unpack(">q", bytes.fromhex(event_id)[:8])[0]
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


@router.post("/alerts", include_in_schema=False)
def receive_alertmanager_webhook(
    payload: AlertmanagerWebhook,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    _require_monitoring_token(authorization)
    accepted = 0
    duplicates = 0
    seen_event_ids: set[str] = set()
    for alert in payload.alerts:
        event_id = _alert_event_id(alert)
        action = f"monitoring.alert.{alert.status}"
        if event_id in seen_event_ids:
            duplicates += 1
            continue
        seen_event_ids.add(event_id)
        _lock_alert_event(db, event_id)
        exists = db.scalar(
            select(AuditLog.id).where(
                AuditLog.action == action,
                AuditLog.entity_type == "monitoring_alert",
                AuditLog.entity_id == event_id,
            )
        )
        if exists is not None:
            duplicates += 1
            continue
        log_audit(
            db,
            action=action,
            entity_type="monitoring_alert",
            entity_id=event_id,
            actor_email="alertmanager@sbs.local",
            metadata={
                "receiver": payload.receiver[:120],
                "fingerprint": alert.fingerprint,
                "labels": _bounded_mapping(alert.labels, limit=40),
                "annotations": _bounded_mapping(alert.annotations, limit=20),
                "starts_at": alert.startsAt[:80],
                "ends_at": alert.endsAt[:80],
                "generator_url": alert.generatorURL[:1000],
            },
        )
        metrics_registry.alertmanager_event_received(alert.status)
        accepted += 1
    db.commit()
    return {"accepted": accepted, "duplicates": duplicates}
