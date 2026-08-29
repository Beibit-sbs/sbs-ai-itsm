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
    for boundary in ("\n    async def ", "\n    def ", "\n\n# ==="):
        body = body.split(boundary, 1)[0]
    return body


def main() -> int:
    service = _read("backend/app/services/jobs/alert_notifications.py")
    routes = _read("backend/app/api/v1/routes/jobs.py")
    settings = _read("backend/app/core/config.py")
    compose = _read("docker-compose.prod.yml")
    preflight = _read("scripts/check-production-env.py")
    initializer = _read("scripts/init-production-secrets.py")
    tests = _read("backend/tests/test_alert_notifications_stage_034.py")
    controls = json.loads(
        _read("security/acceptance-catalog.json")
    )["controls"]

    email = _function(service, "_send_email")
    pagerduty = _function(service, "_send_pagerduty")
    execute = service.split("async def execute_alert(", 1)[1]
    trigger = routes.split("async def trigger_alert_notification(", 1)[1].split(
        "\n\n@router.",
        1,
    )[0]

    _require(
        "smtplib.SMTP" in email
        and "asyncio.to_thread" in email
        and "send_message" in email
        and "if refused:" in email
        and '"sent": False' in email,
        "SMTP delivery is not confirmed and fail-closed",
    )
    _require(
        "stub" not in email.lower()
        and "stub" not in pagerduty.lower()
        and 'f"email-{int(' not in service
        and 'f"pd-{int(' not in service,
        "Alert delivery still contains simulated success evidence",
    )
    _require(
        '"https://events.pagerduty.com/v2/enqueue"' in pagerduty
        and "response.status != 202" in pagerduty
        and "dedup_key" in pagerduty,
        "PagerDuty delivery does not require Events API confirmation",
    )
    _require(
        service.count("allow_redirects=False") >= 3
        and "_configured_destination" in service
        and "deployment-configured" in service
        and "_SLACK_HOSTS" in service,
        "Outbound notification destinations are request-controlled or redirectable",
    )
    _require(
        'delivery_error = "No notification channel confirmed delivery"' in execute
        and '"alert_id": f"alert-{uuid.uuid4()}"' in execute
        and 'if result.get("sent") is True' in execute,
        "Alert execution can report unconfirmed delivery as successful",
    )
    _require(
        "_require_enqueue(current_user)" in trigger
        and "runtime.jobs_alert_smtp_host" in trigger
        and 'action="jobs.alert.delivery_attempted"' in trigger
        and "db.commit()" in trigger,
        "Direct alert execution is not root-only, configured, and audited",
    )

    for field in (
        "jobs_alert_smtp_password",
        "jobs_alert_slack_webhook_url",
        "jobs_alert_pagerduty_routing_key",
        "jobs_alert_webhook_url",
    ):
        _require(field in settings, f"Alert setting is missing: {field}")
        _require(
            compose.count(f"- {field}") >= 3
            and f"{field}:" in compose
            and field in initializer,
            f"Alert secret is not mounted for every application process: {field}",
        )
        _require(
            field.upper() in preflight or field in preflight,
            f"Production preflight omits alert secret: {field}",
        )

    for regression in (
        "test_request_cannot_override_configured_webhook",
        "test_notification_with_empty_recipients",
        "test_send_pagerduty_notification",
        "No notification channel confirmed delivery",
    ):
        _require(regression in tests, f"Alert delivery regression is missing: {regression}")

    control_ids = {str(item["id"]) for item in controls}
    _require(
        "SEC-ALERT-DELIVERY-INTEGRITY" in control_ids,
        "Alert delivery integrity release control is missing",
    )
    print(
        "Alert delivery contract valid: root-only audited execution, "
        "deployment-fixed destinations, Docker-secret configuration, and "
        "transport-confirmed fail-closed results."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Alert delivery contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
