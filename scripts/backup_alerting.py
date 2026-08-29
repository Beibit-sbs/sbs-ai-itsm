"""Alertmanager integration shared by scheduled backup tooling."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from urllib import error, request


def submit_alertmanager_status(
    *,
    base_url: str,
    project_name: str,
    status: str,
    starts_at: str,
    detail: str,
) -> None:
    ends_at = datetime.now(UTC).isoformat() if status == "resolved" else None
    alert = {
        "labels": {
            "alertname": "SbsDatabaseBackupFailed",
            "severity": "critical",
            "project": project_name,
        },
        "annotations": {
            "summary": f"Database backup {status} for {project_name}",
            "description": detail[:1500],
            "runbook": "docs/operations/BACKUP-RESTORE-RUNBOOK.md",
        },
        "startsAt": starts_at,
        "generatorURL": "local://scripts/run-backup.py",
    }
    if ends_at:
        alert["endsAt"] = ends_at
    body = json.dumps([alert]).encode("utf-8")
    http_request = request.Request(
        base_url.rstrip("/") + "/api/v2/alerts",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=10) as response:
            if response.status not in {200, 202}:
                raise RuntimeError(f"Alertmanager returned HTTP {response.status}")
    except error.URLError as exc:
        raise RuntimeError(f"Alertmanager unavailable: {exc.reason}") from exc
