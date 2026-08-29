from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _function(source: str, name: str) -> str:
    marker = f"def {name}("
    _require(marker in source, f"Function is missing: {name}")
    body = source.split(marker, 1)[1]
    return body.split("\n\n@router.", 1)[0]


def main() -> int:
    routes = _read("backend/app/api/v1/routes/jobs.py")
    enforcement = _read(
        "backend/app/services/jobs/policy_canary_enforcement.py"
    )
    monitoring = _read(
        "backend/app/services/jobs/policy_metrics_monitoring.py"
    )
    polling = _read("backend/app/services/jobs/metrics_polling.py")
    collectors = _read(
        "backend/app/services/jobs/alert_notifications.py"
    )
    settings = _read("backend/app/core/config.py")
    preflight = _read("scripts/check-production-env.py")
    migration = _read(
        "backend/migrations/versions/"
        "20260729_0068_invalidate_untrusted_canary_metrics.py"
    )
    tests = (
        _read("backend/tests/test_alert_notifications_stage_034.py")
        + _read("backend/tests/test_metrics_polling_stage_030.py")
        + _read("backend/tests/test_policy_metrics_stage_028.py")
    )
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    _require(
        "_simulate_metrics" not in monitoring
        and "_simulate_metrics" not in polling
        and '"error_rate": 0.48' not in routes
        and "estimated_total_consumers" not in routes,
        "Canary runtime still depends on simulated metrics or consumer counts",
    )
    for field in (
        "baseline_error_rate",
        "baseline_latency_p99_ms",
        "baseline_throughput_eps",
        "metrics_source",
        "evidence_ref",
    ):
        _require(field in routes, f"Canary evidence field is missing: {field}")

    update_body = _function(routes, "update_canary_rollout_metrics")
    graduate_body = _function(routes, "graduate_policy_canary")
    complete_body = _function(routes, "complete_policy_rollout")
    _require(
        "_require_enqueue(current_user)" in update_body
        and "rollout_id must match the route" in update_body,
        "Metrics evidence mutation is not root-only or route-bound",
    )
    _require(
        "evaluate_safe_to_graduate" in graduate_body
        and "HTTP_409_CONFLICT" in graduate_body
        and "previous_percentage" in graduate_body,
        "Canary graduation is not evidence-gated",
    )
    _require(
        "current_canary_percentage != 100" in complete_body
        and "evaluate_safe_to_graduate" in complete_body
        and "HTTP_409_CONFLICT" in complete_body,
        "Rollout completion can bypass the 100% observation gate",
    )
    _require(
        "error_rate_baseline=" in enforcement
        and "metrics_baseline_json = rollout.metrics_current_json" in enforcement
        and "error_rate_current = None" in enforcement,
        "Canary evidence is not promoted and reset between stages",
    )
    _require(
        'raise ValueError("Metrics evidence is required")' in monitoring
        and "Missing evidence must never be represented as safe" in monitoring,
        "Missing metrics evidence is not fail-closed",
    )
    _require(
        "Metrics evidence unavailable" in polling
        and "rollout.error_rate_current is None" in polling,
        "Scheduled evaluation does not stop on missing evidence",
    )

    _require(
        "MetricsCollectionError" in collectors
        and "allow_redirects=False" in collectors
        and "did not return exactly one aggregate" in collectors
        and "math.isfinite" in collectors,
        "Prometheus collection is not bounded and fail-closed",
    )
    _require(
        "prometheus_url: str = Query" not in routes
        and "region: str = Query" not in routes
        and "runtime.prometheus_url" in routes
        and "runtime.cloudwatch_region" in routes,
        "Metrics backend destinations remain request-controlled",
    )
    _require(
        "validate_metrics_backends" in settings
        and "PROMETHEUS_URL must be an explicit HTTP(S) service URL" in settings,
        "Metrics backend configuration validation is missing",
    )
    _require(
        '"PROMETHEUS_URL"' in preflight
        and "check_service_url" in preflight
        and "PROMETHEUS_TIMEOUT_SECONDS bound" in preflight,
        "Production preflight does not validate the metrics destination",
    )

    _require(
        'revision: str = "20260729_0068"' in migration
        and 'down_revision: str | None = "20260729_0067"' in migration
        and "WHERE status = 'in_progress'" in migration,
        "Untrusted in-progress evidence invalidation migration is missing",
    )
    for regression in (
        "test_prometheus_empty_result",
        "test_prometheus_http_error",
        "test_estimate_auto_rollback_confidence_no_data",
        "Metrics evidence unavailable for crl-1",
    ):
        _require(regression in tests, f"Canary regression is missing: {regression}")

    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-CANARY-EVIDENCE-INTEGRITY" in control_ids,
        "Canary evidence integrity release control is missing",
    )
    print(
        "Canary evidence contract valid: simulated production metrics removed, "
        "root-only evidence mutation, fail-closed graduation/completion, "
        "bounded metrics backends."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Canary evidence contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
