from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import Any

from app.models.service_catalog import CatalogItem
from app.models.user import User


RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
ENTITLEMENT_DIMENSIONS = {
    "tenant_ids",
    "user_ids",
    "roles",
    "departments",
    "locations",
    "cost_centers",
}
CALENDAR_CODES = {"24X7", "WEEKDAYS_8X5"}
COST_TYPES = {"NO_CHARGE", "ONE_TIME", "MONTHLY", "ANNUAL"}


def _mapping(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string_list(value: Any, *, field: str, maximum: int = 100) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if len(value) > maximum:
        raise ValueError(f"{field} contains too many values")
    result: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{field} contains an invalid value")
        candidate = raw.strip()
        normalized = candidate.casefold()
        if normalized not in seen:
            result.append(candidate)
            seen.add(normalized)
    return result


def normalize_entitlement_rules(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value or {}
    unsupported = set(raw) - ENTITLEMENT_DIMENSIONS - {"match"}
    if unsupported:
        raise ValueError(
            f"Unsupported entitlement fields: {', '.join(sorted(unsupported))}"
        )
    match = str(raw.get("match") or "ALL").strip().upper()
    if match not in {"ALL", "ANY"}:
        raise ValueError("entitlement match must be ALL or ANY")
    normalized: dict[str, Any] = {"match": match}
    for field in sorted(ENTITLEMENT_DIMENSIONS):
        values = _string_list(raw.get(field), field=field)
        if values:
            normalized[field] = values
    return normalized if len(normalized) > 1 else {}


def normalize_approval_policy(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value or {}
    allowed = {
        "always",
        "cost_threshold_minor",
        "minimum_risk",
        "approver_roles",
        "mode",
        "due_minutes",
    }
    unsupported = set(raw) - allowed
    if unsupported:
        raise ValueError(
            f"Unsupported approval policy fields: {', '.join(sorted(unsupported))}"
        )
    minimum_risk = str(raw.get("minimum_risk") or "").strip().upper()
    if minimum_risk and minimum_risk not in RISK_ORDER:
        raise ValueError("minimum_risk must be LOW, MEDIUM, HIGH, or CRITICAL")
    mode = str(raw.get("mode") or "SEQUENTIAL").strip().upper()
    if mode not in {"SEQUENTIAL", "PARALLEL"}:
        raise ValueError("approval mode must be SEQUENTIAL or PARALLEL")
    threshold = int(raw.get("cost_threshold_minor") or 0)
    if threshold < 0:
        raise ValueError("cost_threshold_minor cannot be negative")
    due_minutes = int(raw.get("due_minutes") or 1440)
    if due_minutes < 5 or due_minutes > 525_600:
        raise ValueError("approval due_minutes must be between 5 and 525600")
    roles = _string_list(raw.get("approver_roles"), field="approver_roles", maximum=20)
    return {
        "always": bool(raw.get("always", False)),
        "cost_threshold_minor": threshold,
        "minimum_risk": minimum_risk or None,
        "approver_roles": roles or ["organization_admin", "it_manager"],
        "mode": mode,
        "due_minutes": due_minutes,
    }


def normalize_sla_policy(
    value: dict[str, Any] | None,
    *,
    default_target_minutes: int,
) -> dict[str, Any]:
    raw = value or {}
    allowed = {
        "target_minutes",
        "ola_minutes",
        "calendar_code",
        "calendar_timezone",
        "warning_percent",
        "pause_on_waiting",
        "escalation_minutes",
    }
    unsupported = set(raw) - allowed
    if unsupported:
        raise ValueError(f"Unsupported SLA fields: {', '.join(sorted(unsupported))}")
    target = int(raw.get("target_minutes") or default_target_minutes)
    if target < 5 or target > 525_600:
        raise ValueError("SLA target_minutes must be between 5 and 525600")
    ola = int(raw.get("ola_minutes") or max(5, int(target * 0.75)))
    if ola < 5 or ola > target:
        raise ValueError("OLA minutes must be between 5 and the SLA target")
    calendar = str(raw.get("calendar_code") or "24X7").strip().upper()
    if calendar not in CALENDAR_CODES:
        raise ValueError("calendar_code must be 24X7 or WEEKDAYS_8X5")
    timezone = str(raw.get("calendar_timezone") or "UTC").strip().upper()
    if timezone != "UTC":
        raise ValueError("calendar_timezone currently must be UTC")
    warning_percent = int(raw.get("warning_percent") or 80)
    if warning_percent < 1 or warning_percent > 99:
        raise ValueError("warning_percent must be between 1 and 99")
    escalation_raw = raw.get("escalation_minutes") or [0, 60, 240]
    if not isinstance(escalation_raw, list) or len(escalation_raw) > 10:
        raise ValueError("escalation_minutes must be a list")
    escalation = sorted({int(entry) for entry in escalation_raw})
    if any(entry < 0 or entry > 525_600 for entry in escalation):
        raise ValueError("escalation_minutes values are out of range")
    return {
        "target_minutes": target,
        "ola_minutes": ola,
        "calendar_code": calendar,
        "calendar_timezone": timezone,
        "warning_percent": warning_percent,
        "pause_on_waiting": bool(raw.get("pause_on_waiting", True)),
        "escalation_minutes": escalation,
    }


def user_role_codes(user: User | None, fallback_role: str | None = None) -> set[str]:
    roles: set[str] = set()
    if user is not None:
        if user.role is not None:
            roles.add(user.role.code.casefold())
        roles.update(role.code.casefold() for role in user.roles)
    if fallback_role:
        roles.add(fallback_role.casefold())
    return roles


def entitlement_decision(
    item: CatalogItem,
    *,
    user: User | None,
    fallback_user_id: str,
    fallback_tenant_id: str | None,
    fallback_role: str,
    bypass: bool = False,
) -> tuple[bool, str]:
    if bypass:
        return True, "Management access"
    try:
        rules = normalize_entitlement_rules(_mapping(item.entitlement_rules_json))
    except ValueError:
        return False, "Catalog entitlement policy is invalid"
    if not rules:
        return True, "Available to all organization users"

    actual = {
        "tenant_ids": {value.casefold() for value in [fallback_tenant_id] if value},
        "user_ids": {fallback_user_id.casefold()},
        "roles": user_role_codes(user, fallback_role),
        "departments": {
            value.casefold() for value in [getattr(user, "department", None)] if value
        },
        "locations": {
            value.casefold() for value in [getattr(user, "location", None)] if value
        },
        "cost_centers": {
            value.casefold() for value in [getattr(user, "cost_center", None)] if value
        },
    }
    checks: list[tuple[str, bool]] = []
    for dimension in ENTITLEMENT_DIMENSIONS:
        expected = {
            str(value).casefold() for value in rules.get(dimension, []) if str(value)
        }
        if expected:
            checks.append((dimension, bool(expected & actual[dimension])))
    if not checks:
        return True, "Available to all organization users"
    match = str(rules.get("match") or "ALL")
    allowed = all(result for _, result in checks) if match == "ALL" else any(
        result for _, result in checks
    )
    failed = [dimension for dimension, result in checks if not result]
    return (
        (True, f"Entitlement matched ({match.lower()})")
        if allowed
        else (False, f"Entitlement does not match: {', '.join(failed)}")
    )


def approval_decision(
    item: CatalogItem,
    *,
    total_cost_minor: int,
) -> tuple[bool, dict[str, Any], list[str]]:
    policy = normalize_approval_policy(_mapping(item.approval_policy_json))
    reasons: list[str] = []
    if item.approval_required:
        reasons.append("catalog item requires approval")
    if policy["always"]:
        reasons.append("approval policy is always-on")
    threshold = int(policy["cost_threshold_minor"])
    if threshold and total_cost_minor >= threshold:
        reasons.append(f"cost threshold reached ({threshold})")
    minimum_risk = policy["minimum_risk"]
    if minimum_risk and RISK_ORDER[item.risk_level] >= RISK_ORDER[minimum_risk]:
        reasons.append(f"risk is {item.risk_level}")
    return bool(reasons), policy, reasons


def add_service_minutes(
    start: datetime,
    minutes: int,
    calendar_code: str,
) -> datetime:
    current = start.astimezone(UTC)
    if calendar_code == "24X7":
        return current + timedelta(minutes=minutes)
    remaining = minutes
    while remaining > 0:
        if current.weekday() >= 5:
            current = (current + timedelta(days=7 - current.weekday())).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            continue
        work_start = current.replace(hour=9, minute=0, second=0, microsecond=0)
        work_end = current.replace(hour=17, minute=0, second=0, microsecond=0)
        if current < work_start:
            current = work_start
        if current >= work_end:
            current = (current + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0
            )
            continue
        available = int((work_end - current).total_seconds() // 60)
        consumed = min(remaining, available)
        current += timedelta(minutes=consumed)
        remaining -= consumed
    return current


def sla_status(
    *,
    started_at: datetime | None,
    due_at: datetime | None,
    paused_at: datetime | None,
    completed_at: datetime | None,
    breached_at: datetime | None,
    policy: dict[str, Any],
    now: datetime | None = None,
) -> str:
    if started_at is None or due_at is None:
        return "NOT_STARTED"
    timestamp = now or datetime.now(UTC)
    timestamp = (
        timestamp.replace(tzinfo=UTC)
        if timestamp.tzinfo is None
        else timestamp.astimezone(UTC)
    )
    started_at = (
        started_at.replace(tzinfo=UTC)
        if started_at.tzinfo is None
        else started_at.astimezone(UTC)
    )
    due_at = (
        due_at.replace(tzinfo=UTC)
        if due_at.tzinfo is None
        else due_at.astimezone(UTC)
    )
    if paused_at is not None and completed_at is None:
        return "PAUSED"
    if breached_at is not None or timestamp > due_at:
        return "BREACHED"
    if completed_at is not None:
        return "MET"
    total = max(1, (due_at - started_at).total_seconds())
    consumed = max(0, (timestamp - started_at).total_seconds())
    if consumed / total * 100 >= int(policy.get("warning_percent") or 80):
        return "AT_RISK"
    return "ACTIVE"
