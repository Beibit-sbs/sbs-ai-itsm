from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job_event_runbook_policy_state import JobEventRunbookPolicyState

RUNBOOK_POLICY_STATE_ID = "jobs_event_runbook_policy"


class RunbookPolicyVersionConflictError(RuntimeError):
    pass


def _default_payload(settings) -> dict[str, Any]:
    return {
        "allowed_codes": [str(item) for item in settings.jobs_event_runbook_allowed_codes if str(item).strip()],
        "denied_codes": [str(item) for item in settings.jobs_event_runbook_denied_codes if str(item).strip()],
        "high_impact_codes": [str(item) for item in settings.jobs_event_runbook_high_impact_codes if str(item).strip()],
        "cooldown_seconds_map": (
            settings.jobs_event_runbook_cooldown_seconds_map
            if isinstance(settings.jobs_event_runbook_cooldown_seconds_map, dict)
            else {}
        ),
        "require_change_ticket": bool(settings.jobs_event_runbook_require_change_ticket),
        "dual_control_required": bool(settings.jobs_event_runbook_dual_control_required),
    }


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _deserialize(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _apply_payload_to_settings(settings, payload: dict[str, Any]) -> None:
    allowed_codes = payload.get("allowed_codes", [])
    denied_codes = payload.get("denied_codes", [])
    high_impact_codes = payload.get("high_impact_codes", [])

    settings.jobs_event_runbook_allowed_codes = (
        [str(item) for item in allowed_codes if str(item).strip()] if isinstance(allowed_codes, list) else []
    )
    settings.jobs_event_runbook_denied_codes = (
        [str(item) for item in denied_codes if str(item).strip()] if isinstance(denied_codes, list) else []
    )
    settings.jobs_event_runbook_high_impact_codes = (
        [str(item) for item in high_impact_codes if str(item).strip()] if isinstance(high_impact_codes, list) else []
    )

    cooldown_map_raw = payload.get("cooldown_seconds_map", {})
    cooldown_map: dict[str, int] = {}
    if isinstance(cooldown_map_raw, dict):
        for key, value in cooldown_map_raw.items():
            code = str(key).strip()
            if not code:
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            cooldown_map[code] = max(0, parsed)
    settings.jobs_event_runbook_cooldown_seconds_map = cooldown_map

    settings.jobs_event_runbook_require_change_ticket = bool(payload.get("require_change_ticket", True))
    settings.jobs_event_runbook_dual_control_required = bool(payload.get("dual_control_required", False))


def ensure_runbook_policy_state(
    db: Session,
    settings,
    *,
    actor_email: str = "system@sbs.local",
) -> JobEventRunbookPolicyState:
    row = db.scalar(select(JobEventRunbookPolicyState).where(JobEventRunbookPolicyState.id == RUNBOOK_POLICY_STATE_ID))
    if row is not None:
        return row

    payload = _default_payload(settings)
    row = JobEventRunbookPolicyState(
        id=RUNBOOK_POLICY_STATE_ID,
        version=1,
        payload_json=_serialize(payload),
        updated_by_email=actor_email,
    )
    db.add(row)
    db.flush()
    return row


def load_runbook_policy_into_settings(db: Session, settings) -> dict[str, Any]:
    row = ensure_runbook_policy_state(db, settings)
    payload = _deserialize(row.payload_json)
    _apply_payload_to_settings(settings, payload)
    return {
        "version": int(row.version),
        "payload": payload,
        "updated_by_email": row.updated_by_email,
        "updated_at": row.updated_at,
    }


def save_runbook_policy(
    db: Session,
    settings,
    *,
    payload: dict[str, Any],
    expected_version: int,
    actor_email: str,
) -> dict[str, Any]:
    row = ensure_runbook_policy_state(db, settings, actor_email=actor_email)
    if int(row.version) != int(expected_version):
        raise RunbookPolicyVersionConflictError(
            f"Runbook policy version mismatch: expected {expected_version}, current {row.version}"
        )

    row.version = int(row.version) + 1
    row.payload_json = _serialize(payload)
    row.updated_by_email = actor_email
    db.flush()

    _apply_payload_to_settings(settings, payload)
    return {
        "version": int(row.version),
        "payload": payload,
        "updated_by_email": row.updated_by_email,
        "updated_at": row.updated_at,
    }
