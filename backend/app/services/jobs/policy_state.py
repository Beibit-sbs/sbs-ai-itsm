from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.job_event_autoremediation_policy_state import JobEventAutoremediationPolicyState

POLICY_STATE_ID = "jobs_event_autoremediation_policy"


class PolicyVersionConflictError(RuntimeError):
    pass


def _default_payload(settings) -> dict[str, Any]:
    return {
        "policy_profiles": settings.jobs_event_autoremediation_policy_profiles
        if isinstance(settings.jobs_event_autoremediation_policy_profiles, dict)
        else {},
        "suppression_windows_utc": [
            str(item) for item in settings.jobs_event_autoremediation_suppression_windows_utc if str(item).strip()
        ],
        "error_denylist": [str(item) for item in settings.jobs_event_autoremediation_error_denylist if str(item).strip()],
        "canary_mode": bool(settings.jobs_event_autoremediation_canary_mode),
        "canary_limit_per_cycle": int(settings.jobs_event_autoremediation_canary_limit_per_cycle),
        "burst_max_per_10m": int(settings.jobs_event_autoremediation_burst_max_per_10m),
        "brake_error_threshold": int(settings.jobs_event_autoremediation_brake_error_threshold),
        "braked_consumers": [str(item) for item in settings.jobs_event_autoremediation_braked_consumers if str(item).strip()],
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
    profile_map = payload.get("policy_profiles", {})
    settings.jobs_event_autoremediation_policy_profiles = profile_map if isinstance(profile_map, dict) else {}

    suppression_windows = payload.get("suppression_windows_utc", [])
    settings.jobs_event_autoremediation_suppression_windows_utc = (
        [str(item) for item in suppression_windows if str(item).strip()]
        if isinstance(suppression_windows, list)
        else []
    )

    denylist = payload.get("error_denylist", [])
    settings.jobs_event_autoremediation_error_denylist = (
        [str(item) for item in denylist if str(item).strip()] if isinstance(denylist, list) else []
    )

    settings.jobs_event_autoremediation_canary_mode = bool(payload.get("canary_mode", False))
    settings.jobs_event_autoremediation_canary_limit_per_cycle = max(
        0,
        int(payload.get("canary_limit_per_cycle", settings.jobs_event_autoremediation_canary_limit_per_cycle)),
    )
    settings.jobs_event_autoremediation_burst_max_per_10m = max(
        0,
        int(payload.get("burst_max_per_10m", settings.jobs_event_autoremediation_burst_max_per_10m)),
    )
    settings.jobs_event_autoremediation_brake_error_threshold = max(
        0,
        int(payload.get("brake_error_threshold", settings.jobs_event_autoremediation_brake_error_threshold)),
    )
    braked_consumers = payload.get("braked_consumers", [])
    settings.jobs_event_autoremediation_braked_consumers = (
        [str(item) for item in braked_consumers if str(item).strip()] if isinstance(braked_consumers, list) else []
    )


def ensure_policy_state(db: Session, settings, *, actor_email: str = "system@sbs.local") -> JobEventAutoremediationPolicyState:
    row = db.scalar(
        select(JobEventAutoremediationPolicyState).where(JobEventAutoremediationPolicyState.id == POLICY_STATE_ID)
    )
    if row is not None:
        return row

    payload = _default_payload(settings)
    row = JobEventAutoremediationPolicyState(
        id=POLICY_STATE_ID,
        version=1,
        payload_json=_serialize(payload),
        updated_by_email=actor_email,
    )
    db.add(row)
    db.flush()
    return row


def load_policy_into_settings(db: Session, settings) -> dict[str, Any]:
    row = ensure_policy_state(db, settings)
    payload = _deserialize(row.payload_json)
    _apply_payload_to_settings(settings, payload)
    return {
        "version": int(row.version),
        "payload": payload,
        "updated_by_email": row.updated_by_email,
        "updated_at": row.updated_at,
    }


def save_policy(
    db: Session,
    settings,
    *,
    payload: dict[str, Any],
    expected_version: int,
    actor_email: str,
) -> dict[str, Any]:
    row = ensure_policy_state(db, settings, actor_email=actor_email)
    if int(row.version) != int(expected_version):
        raise PolicyVersionConflictError(
            f"Policy version mismatch: expected {expected_version}, current {row.version}"
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
