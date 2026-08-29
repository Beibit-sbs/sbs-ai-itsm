#!/usr/bin/env python3
"""Create and restore PostgreSQL custom-format snapshots through Docker Compose."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib import error, request


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from backup_alerting import submit_alertmanager_status  # noqa: E402
from backup_crypto import decrypt_file, encrypt_file, load_backup_key  # noqa: E402


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def compose_base(
    *,
    project_name: str,
    compose_file: Path,
    env_file: Path,
) -> list[str]:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker CLI is not available")
    return [
        docker,
        "compose",
        "--project-name",
        project_name,
        "-f",
        str(compose_file),
        "--env-file",
        str(env_file),
    ]


def ensure_postgres_running(command: list[str], *, root: Path) -> None:
    completed = subprocess.run(
        [*command, "ps", "--status", "running", "-q", "postgres"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("PostgreSQL service is not running in the selected Compose project")


def database_revision(
    command: list[str],
    *,
    root: Path,
    postgres_user: str,
    postgres_db: str,
) -> str:
    completed = subprocess.run(
        [
            *command,
            "exec",
            "-T",
            "postgres",
            "psql",
            "--username",
            postgres_user,
            "--dbname",
            postgres_db,
            "--tuples-only",
            "--no-align",
            "--command",
            "SELECT version_num FROM alembic_version LIMIT 1",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("could not read the database migration revision")
    return completed.stdout.strip().splitlines()[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_snapshot(
    command: list[str],
    *,
    root: Path,
    output: Path,
    postgres_user: str,
    postgres_db: str,
) -> None:
    if output.exists():
        raise RuntimeError(f"refusing to overwrite existing snapshot: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    pg_dump = [
        *command,
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "--username",
        postgres_user,
        "--dbname",
        postgres_db,
        "--format=custom",
        "--compress=6",
        "--no-owner",
        "--no-privileges",
    ]
    with output.open("wb") as destination:
        completed = subprocess.run(
            pg_dump,
            cwd=root,
            stdout=destination,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
    if completed.returncode != 0:
        output.unlink(missing_ok=True)
        detail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(detail[-1][:240] if detail else "pg_dump failed")
    if output.stat().st_size < 1024:
        output.unlink(missing_ok=True)
        raise RuntimeError("snapshot is unexpectedly small")


def restore_snapshot(
    command: list[str],
    *,
    root: Path,
    snapshot: Path,
    postgres_user: str,
    postgres_db: str,
) -> None:
    if not snapshot.is_file() or snapshot.stat().st_size < 1024:
        raise RuntimeError("snapshot is missing or unexpectedly small")
    pg_restore = [
        *command,
        "exec",
        "-T",
        "postgres",
        "pg_restore",
        "--username",
        postgres_user,
        "--dbname",
        postgres_db,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--single-transaction",
        "--exit-on-error",
    ]
    with snapshot.open("rb") as source:
        completed = subprocess.run(
            pg_restore,
            cwd=root,
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=600,
            check=False,
        )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(detail[-1][:240] if detail else "pg_restore failed")


def write_manifest(
    *,
    snapshot: Path,
    project_name: str,
    revision: str,
    encrypted: bool,
    started_at: datetime,
    duration_seconds: float,
) -> Path:
    manifest = {
        "format": "sbs-postgresql-backup-v1",
        "created_at": started_at.isoformat(),
        "project_name": project_name,
        "database_revision": revision,
        "encrypted": encrypted,
        "algorithm": "AES-256-GCM" if encrypted else None,
        "artifact": snapshot.name,
        "artifact_bytes": snapshot.stat().st_size,
        "artifact_sha256": sha256_file(snapshot),
        "duration_seconds": round(duration_seconds, 3),
    }
    manifest_path = snapshot.with_name(snapshot.name + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def verify_manifest(snapshot: Path) -> dict[str, object] | None:
    manifest_path = snapshot.with_name(snapshot.name + ".manifest.json")
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_sha256") != sha256_file(snapshot):
        raise RuntimeError("snapshot checksum does not match its manifest")
    return manifest


def notify_backup_status(
    *,
    url: str,
    token_file: Path,
    project_name: str,
    status: str,
    starts_at: str,
    detail: str,
) -> None:
    token = token_file.read_text(encoding="utf-8").strip()
    if len(token) < 24:
        raise RuntimeError("monitoring token is missing or too short")
    fingerprint = hashlib.sha256(
        f"sbs-backup:{project_name}".encode("utf-8")
    ).hexdigest()[:32]
    severity = "critical" if status == "firing" else "info"
    payload = {
        "version": "4",
        "groupKey": f'{{}}:{{alertname="SbsDatabaseBackupFailed",project="{project_name}"}}',
        "status": status,
        "receiver": "sbs-platform",
        "groupLabels": {"alertname": "SbsDatabaseBackupFailed"},
        "commonLabels": {"project": project_name},
        "commonAnnotations": {},
        "externalURL": "",
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "SbsDatabaseBackupFailed",
                    "severity": severity,
                    "project": project_name,
                },
                "annotations": {
                    "summary": f"Database backup {status} for {project_name}",
                    "description": detail[:1500],
                    "runbook": "docs/operations/BACKUP-RESTORE-RUNBOOK.md",
                },
                "startsAt": starts_at,
                "endsAt": datetime.now(UTC).isoformat() if status == "resolved" else "",
                "generatorURL": "local://scripts/postgres-snapshot.py",
                "fingerprint": fingerprint,
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"monitoring webhook returned HTTP {response.status}")
    except error.URLError as exc:
        raise RuntimeError(f"monitoring webhook unavailable: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "restore"))
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--compose-file", type=Path, default=Path("docker-compose.prod.yml"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument(
        "--encryption-key-file",
        type=Path,
        help="encrypt backups and decrypt restores with this non-versioned secret",
    )
    parser.add_argument("--notify-url", default="")
    parser.add_argument("--notify-token-file", type=Path)
    parser.add_argument(
        "--alertmanager-url",
        default="",
        help="submit firing/resolved backup alerts to Alertmanager API",
    )
    parser.add_argument(
        "--confirm-restore",
        action="store_true",
        help="required for restore because existing target objects are replaced",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    env_file = args.env_file if args.env_file.is_absolute() else root / args.env_file
    compose_file = (
        args.compose_file if args.compose_file.is_absolute() else root / args.compose_file
    )
    if not env_file.is_file() or not compose_file.is_file():
        print("[FAIL] env or Compose file not found", file=sys.stderr)
        return 1
    values = load_env(env_file)
    postgres_user = values.get("POSTGRES_USER", "")
    postgres_db = values.get("POSTGRES_DB", "")
    if not postgres_user or not postgres_db:
        print("[FAIL] POSTGRES_USER and POSTGRES_DB are required", file=sys.stderr)
        return 1

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    default_suffix = ".dump.enc" if args.encryption_key_file else ".dump"
    snapshot = (
        args.snapshot
        or Path("backups/db") / f"{timestamp}_{args.project_name}{default_suffix}"
    )
    snapshot = snapshot if snapshot.is_absolute() else root / snapshot
    encryption_key_file = args.encryption_key_file
    if encryption_key_file and not encryption_key_file.is_absolute():
        encryption_key_file = root / encryption_key_file
    notify_token_file = args.notify_token_file
    if notify_token_file and not notify_token_file.is_absolute():
        notify_token_file = root / notify_token_file
    if bool(args.notify_url) != bool(notify_token_file):
        print(
            "[FAIL] --notify-url and --notify-token-file must be provided together",
            file=sys.stderr,
        )
        return 1
    event_started_at = datetime.now(UTC).isoformat()
    operation_started_at = datetime.now(UTC)
    timer = time.perf_counter()
    try:
        command = compose_base(
            project_name=args.project_name,
            compose_file=compose_file.resolve(),
            env_file=env_file.resolve(),
        )
        ensure_postgres_running(command, root=root)
        if args.action == "backup":
            revision = database_revision(
                command,
                root=root,
                postgres_user=postgres_user,
                postgres_db=postgres_db,
            )
            if encryption_key_file:
                if not encryption_key_file.is_file():
                    raise RuntimeError("backup encryption key file does not exist")
                if snapshot.exists():
                    raise RuntimeError(f"refusing to overwrite existing snapshot: {snapshot}")
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(
                    dir=snapshot.parent, prefix=".database-backup-"
                ) as temp_dir:
                    plain_snapshot = Path(temp_dir) / "snapshot.dump"
                    create_snapshot(
                        command,
                        root=root,
                        output=plain_snapshot,
                        postgres_user=postgres_user,
                        postgres_db=postgres_db,
                    )
                    encrypt_file(
                        plain_snapshot,
                        snapshot,
                        load_backup_key(encryption_key_file),
                    )
            else:
                create_snapshot(
                    command,
                    root=root,
                    output=snapshot,
                    postgres_user=postgres_user,
                    postgres_db=postgres_db,
                )
            duration = time.perf_counter() - timer
            manifest_path = write_manifest(
                snapshot=snapshot,
                project_name=args.project_name,
                revision=revision,
                encrypted=bool(encryption_key_file),
                started_at=operation_started_at,
                duration_seconds=duration,
            )
            print(
                f"Snapshot created: {snapshot} "
                f"(bytes={snapshot.stat().st_size}, sha256={sha256_file(snapshot)}, "
                f"revision={revision}, manifest={manifest_path})"
            )
            if args.notify_url and notify_token_file:
                notify_backup_status(
                    url=args.notify_url,
                    token_file=notify_token_file,
                    project_name=args.project_name,
                    status="resolved",
                    starts_at=event_started_at,
                    detail=f"Encrypted backup completed in {duration:.3f} seconds",
                )
            if args.alertmanager_url:
                submit_alertmanager_status(
                    base_url=args.alertmanager_url,
                    project_name=args.project_name,
                    status="resolved",
                    starts_at=event_started_at,
                    detail=f"Encrypted backup completed in {duration:.3f} seconds",
                )
        else:
            if not args.confirm_restore:
                raise RuntimeError("restore blocked; pass --confirm-restore")
            verify_manifest(snapshot)
            if snapshot.name.endswith(".enc"):
                if not encryption_key_file or not encryption_key_file.is_file():
                    raise RuntimeError(
                        "encrypted restore requires --encryption-key-file"
                    )
                with tempfile.TemporaryDirectory(
                    dir=snapshot.parent, prefix=".database-restore-"
                ) as temp_dir:
                    plain_snapshot = Path(temp_dir) / "snapshot.dump"
                    decrypt_file(
                        snapshot,
                        plain_snapshot,
                        load_backup_key(encryption_key_file),
                    )
                    restore_snapshot(
                        command,
                        root=root,
                        snapshot=plain_snapshot,
                        postgres_user=postgres_user,
                        postgres_db=postgres_db,
                    )
            else:
                restore_snapshot(
                    command,
                    root=root,
                    snapshot=snapshot,
                    postgres_user=postgres_user,
                    postgres_db=postgres_db,
                )
            print(
                f"Snapshot restored: {snapshot} "
                f"(sha256={sha256_file(snapshot)})"
            )
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as exc:
        if args.action == "backup" and args.notify_url and notify_token_file:
            try:
                notify_backup_status(
                    url=args.notify_url,
                    token_file=notify_token_file,
                    project_name=args.project_name,
                    status="firing",
                    starts_at=event_started_at,
                    detail=str(exc),
                )
            except (OSError, RuntimeError) as notify_exc:
                print(f"[WARN] backup alert delivery failed: {notify_exc}", file=sys.stderr)
        if args.action == "backup" and args.alertmanager_url:
            try:
                submit_alertmanager_status(
                    base_url=args.alertmanager_url,
                    project_name=args.project_name,
                    status="firing",
                    starts_at=event_started_at,
                    detail=str(exc),
                )
            except (OSError, RuntimeError) as notify_exc:
                print(
                    f"[WARN] Alertmanager backup alert failed: {notify_exc}",
                    file=sys.stderr,
                )
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
