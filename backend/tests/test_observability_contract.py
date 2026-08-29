from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_slo_catalog_covers_critical_services() -> None:
    catalog = json.loads(
        (ROOT / "monitoring" / "slo-catalog.json").read_text(encoding="utf-8")
    )
    services = catalog["services"]
    covered = {item["service"] for item in services}

    assert {
        "api",
        "jobs-worker",
        "scheduler",
        "delivery",
        "ai-provider",
        "sla-engine",
    } <= covered
    assert len({item["id"] for item in services}) == len(services)
    assert all(item["owner"] and item["runbook"] for item in services)


def test_every_prometheus_alert_has_owner_severity_and_runbook() -> None:
    text = (
        ROOT / "monitoring" / "prometheus" / "alerts.yml"
    ).read_text(encoding="utf-8")
    alert_names = re.findall(r"^\s+- alert: ([A-Za-z0-9_]+)\s*$", text, re.M)

    assert len(alert_names) >= 15
    for alert_name in alert_names:
        start = text.index(f"- alert: {alert_name}")
        next_match = re.search(r"^\s+- alert: ", text[start + 1 :], re.M)
        end = start + 1 + next_match.start() if next_match else len(text)
        block = text[start:end]
        assert re.search(r"^\s+owner:\s+\S+", block, re.M), alert_name
        assert re.search(
            r"^\s+severity:\s+(critical|warning|info)", block, re.M
        ), alert_name
        assert re.search(r"^\s+runbook_url:\s+\S+", block, re.M), alert_name


def test_operational_metrics_are_low_cardinality_and_secrets_safe() -> None:
    source = (
        ROOT / "backend" / "app" / "services" / "operational_metrics.py"
    ).read_text(encoding="utf-8")

    for forbidden_label in (
        "tenant_id=",
        "user_id=",
        "ticket_id=",
        "email=",
        "correlation_id=",
        "prompt=",
        "token=",
    ):
        assert forbidden_label not in source
    assert "sbs_job_queue_oldest_age_seconds" in source
    assert "sbs_delivery_queue_oldest_age_seconds" in source
    assert "sbs_ai_requests_window" in source
    assert "sbs_sla_breaches_window" in source
    assert "sbs_scheduler_ready" in source
    assert "sbs_auth_events_window" in source
    assert "sbs_attachment_scan_items" in source


def test_dashboard_covers_platform_and_business_signals() -> None:
    dashboard = json.loads(
        (
            ROOT
            / "monitoring"
            / "grafana"
            / "dashboards"
            / "sbs-platform-overview.json"
        ).read_text(encoding="utf-8")
    )
    titles = {panel["title"] for panel in dashboard["panels"]}

    assert dashboard["uid"] == "sbs-platform-overview"
    assert {
        "Backend availability",
        "P95 latency",
        "Job queue depth",
        "Scheduler readiness",
        "Delivery queue lag",
        "Authentication failures",
        "Attachment scan status",
        "AI provider outcomes",
        "Recent SLA breaches",
    } <= titles
