from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "monitoring" / "slo-catalog.json"
ALERTS_PATH = ROOT / "monitoring" / "prometheus" / "alerts.yml"
DASHBOARD_PATH = (
    ROOT
    / "monitoring"
    / "grafana"
    / "dashboards"
    / "sbs-platform-overview.json"
)
REQUIRED_SERVICES = {
    "api",
    "jobs-worker",
    "scheduler",
    "delivery",
    "ai-provider",
    "sla-engine",
}
REQUIRED_FIELDS = {
    "id",
    "service",
    "owner",
    "sli",
    "objective",
    "window",
    "query",
    "alert",
    "dashboard_uid",
    "runbook",
}


def _fail(message: str) -> None:
    raise ValueError(message)


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    alerts_text = ALERTS_PATH.read_text(encoding="utf-8")
    dashboard = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    services = catalog.get("services")
    if not isinstance(services, list) or not services:
        _fail("SLO catalog must contain a non-empty services list")

    seen_ids: set[str] = set()
    covered_services: set[str] = set()
    for index, item in enumerate(services):
        if not isinstance(item, dict):
            _fail(f"SLO entry {index} must be an object")
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            _fail(f"SLO entry {index} misses fields: {sorted(missing)}")
        if not all(str(item[field]).strip() for field in REQUIRED_FIELDS):
            _fail(f"SLO entry {index} contains an empty required field")
        slo_id = str(item["id"])
        if slo_id in seen_ids:
            _fail(f"Duplicate SLO id: {slo_id}")
        seen_ids.add(slo_id)
        covered_services.add(str(item["service"]))
        alert = str(item["alert"])
        if f"- alert: {alert}" not in alerts_text:
            _fail(f"SLO {slo_id} references missing alert {alert}")
        if item["dashboard_uid"] != dashboard.get("uid"):
            _fail(f"SLO {slo_id} references an unknown dashboard")
        runbook_path = str(item["runbook"]).split("#", maxsplit=1)[0]
        if not (ROOT / runbook_path).exists():
            _fail(f"SLO {slo_id} references missing runbook {runbook_path}")

    missing_services = REQUIRED_SERVICES - covered_services
    if missing_services:
        _fail(f"Critical services without an SLO: {sorted(missing_services)}")

    alert_names = re.findall(r"^\s+- alert: ([A-Za-z0-9_]+)\s*$", alerts_text, re.M)
    for alert_name in alert_names:
        start = alerts_text.index(f"- alert: {alert_name}")
        next_match = re.search(r"^\s+- alert: ", alerts_text[start + 1 :], re.M)
        end = start + 1 + next_match.start() if next_match else len(alerts_text)
        block = alerts_text[start:end]
        if not re.search(r"^\s+owner:\s+\S+", block, re.M):
            _fail(f"Alert {alert_name} has no owner label")
        if not re.search(r"^\s+severity:\s+(critical|warning|info)", block, re.M):
            _fail(f"Alert {alert_name} has no supported severity")
        if not re.search(r"^\s+runbook_url:\s+\S+", block, re.M):
            _fail(f"Alert {alert_name} has no runbook URL")

    panel_titles = {
        str(panel.get("title", "")).strip()
        for panel in dashboard.get("panels", [])
        if isinstance(panel, dict)
    }
    required_panels = {
        "Backend availability",
        "P95 latency",
        "Job queue depth",
        "Scheduler readiness",
        "Delivery queue lag",
        "Authentication failures",
        "Attachment scan status",
        "AI provider outcomes",
        "Recent SLA breaches",
    }
    if missing_panels := required_panels - panel_titles:
        _fail(f"Dashboard misses panels: {sorted(missing_panels)}")

    print(
        "Observability contract valid: "
        f"{len(services)} SLOs, {len(alert_names)} alerts, "
        f"{len(panel_titles)} panels."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Observability contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
