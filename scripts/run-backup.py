#!/usr/bin/env python3
"""Run one encrypted database + runtime-data backup transaction."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
import time

from backup_alerting import submit_alertmanager_status


def _run(command: list[str], *, root: Path, label: str) -> None:
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if completed.returncode != 0:
        lines = (completed.stderr or completed.stdout).strip().splitlines()
        detail = lines[-1][:500] if lines else f"{label} exited with no diagnostic"
        raise RuntimeError(f"{label} failed: {detail}")
    if completed.stdout.strip():
        print(completed.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--compose-file", type=Path, default=Path("docker-compose.prod.yml"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--encryption-key-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("backups/scheduled"))
    parser.add_argument("--alertmanager-url", required=True)
    parser.add_argument("--apply-retention", action="store_true")
    parser.add_argument("--daily", type=int, default=7)
    parser.add_argument("--weekly", type=int, default=4)
    parser.add_argument("--monthly", type=int, default=6)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    event_started_at = datetime.now(UTC).isoformat()
    output_root = args.output_root if args.output_root.is_absolute() else root / args.output_root
    database_artifact = (
        output_root / "database" / f"{timestamp}_{args.project_name}.dump.enc"
    )
    data_artifact = output_root / "data" / f"{timestamp}_runtime-data.tar.gz.enc"
    run_manifest = output_root / "runs" / f"{timestamp}_{args.project_name}.json"
    started = time.perf_counter()
    try:
        _run(
            [
                sys.executable,
                str(root / "scripts" / "postgres-snapshot.py"),
                "backup",
                "--project-name",
                args.project_name,
                "--compose-file",
                str(args.compose_file),
                "--env-file",
                str(args.env_file),
                "--snapshot",
                str(database_artifact),
                "--encryption-key-file",
                str(args.encryption_key_file),
            ],
            root=root,
            label="database backup",
        )
        _run(
            [
                sys.executable,
                str(root / "scripts" / "runtime-data-backup.py"),
                "backup",
                "--archive",
                str(data_artifact),
                "--encryption-key-file",
                str(args.encryption_key_file),
            ],
            root=root,
            label="runtime-data backup",
        )
        retention_command = [
            sys.executable,
            str(root / "scripts" / "backup-retention.py"),
            "--root",
            str(output_root),
            "--daily",
            str(args.daily),
            "--weekly",
            str(args.weekly),
            "--monthly",
            str(args.monthly),
        ]
        if args.apply_retention:
            retention_command.append("--apply")
        _run(retention_command, root=root, label="retention")
        database_manifest = json.loads(
            database_artifact.with_name(
                database_artifact.name + ".manifest.json"
            ).read_text(encoding="utf-8")
        )
        data_manifest = json.loads(
            data_artifact.with_name(data_artifact.name + ".manifest.json").read_text(
                encoding="utf-8"
            )
        )
        result = {
            "format": "sbs-backup-run-v1",
            "status": "success",
            "project_name": args.project_name,
            "started_at": event_started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "duration_seconds": round(time.perf_counter() - started, 3),
            "database": database_manifest,
            "runtime_data": data_manifest,
            "retention": {
                "daily": args.daily,
                "weekly": args.weekly,
                "monthly": args.monthly,
                "applied": args.apply_retention,
            },
        }
        run_manifest.parent.mkdir(parents=True, exist_ok=True)
        run_manifest.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        submit_alertmanager_status(
            base_url=args.alertmanager_url,
            project_name=args.project_name,
            status="resolved",
            starts_at=event_started_at,
            detail=(
                f"Encrypted database and runtime-data backups completed in "
                f"{result['duration_seconds']} seconds"
            ),
        )
        print(f"Backup run completed: {run_manifest}")
        return 0
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as exc:
        try:
            submit_alertmanager_status(
                base_url=args.alertmanager_url,
                project_name=args.project_name,
                status="firing",
                starts_at=event_started_at,
                detail=str(exc),
            )
        except (OSError, RuntimeError) as alert_exc:
            print(f"[WARN] backup alert delivery failed: {alert_exc}", file=sys.stderr)
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
