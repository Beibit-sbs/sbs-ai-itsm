#!/usr/bin/env python3
"""Create a non-versioned Docker secrets directory for production deployment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import quote


def _random_secret(bytes_count: int = 36) -> str:
    return secrets.token_urlsafe(bytes_count)


def _write_secret(directory: Path, name: str, value: str) -> None:
    path = directory / name
    if path.exists():
        raise RuntimeError(f"refusing to overwrite existing secret: {path}")
    # Docker secrets are consumed by Linux containers. Writing bytes avoids
    # Windows text-mode CRLF conversion, which changes password values read by
    # shell command substitution (the trailing LF is removed, but CR is not).
    path.write_bytes((value + "\n").encode("utf-8"))
    if os.name != "nt":
        path.chmod(0o600)


def _normalize_existing_secrets(directory: Path) -> int:
    if not directory.is_dir():
        print(f"[FAIL] secret directory does not exist: {directory}", file=sys.stderr)
        return 1
    paths = sorted(path for path in directory.iterdir() if path.is_file())
    if not paths:
        print(f"[FAIL] no secret files found in {directory}", file=sys.stderr)
        return 1

    changed = 0
    for path in paths:
        raw_value = path.read_bytes()
        if b"\x00" in raw_value:
            print(f"[FAIL] refusing to normalize binary secret: {path.name}", file=sys.stderr)
            return 1
        normalized = raw_value.rstrip(b"\r\n") + b"\n"
        if normalized != raw_value:
            path.write_bytes(normalized)
            changed += 1
        if os.name != "nt":
            path.chmod(0o600)

    print(f"Normalized {changed} of {len(paths)} secret files to LF endings in {directory}")
    return 0


def _ensure_additive_secrets(directory: Path) -> int:
    """Add independently rotatable secrets introduced after first deployment."""
    if not directory.is_dir():
        print(f"[FAIL] secret directory does not exist: {directory}", file=sys.stderr)
        return 1

    values = {
        "credential_encryption_key": _random_secret(48),
        "configuration_package_signing_key": _random_secret(48),
        "oidc_client_secret": "disabled-" + _random_secret(24),
        "jobs_alert_smtp_password": "disabled-" + _random_secret(24),
        "jobs_alert_slack_webhook_url": "disabled-" + _random_secret(24),
        "jobs_alert_pagerduty_routing_key": "disabled-" + _random_secret(24),
        "jobs_alert_webhook_url": "disabled-" + _random_secret(24),
        "smoke_user_password": "S9!" + _random_secret(36),
        "smoke_user_secondary_password": "S9!" + _random_secret(36),
        "performance_user_password": "S9!" + _random_secret(36),
    }
    created: list[str] = []
    for name, value in values.items():
        if (directory / name).exists():
            continue
        _write_secret(directory, name, value)
        created.append(name)

    print(
        f"Created {len(created)} missing additive secret files in {directory}; "
        "existing values were preserved"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("secrets"))
    parser.add_argument("--postgres-user", default="sbs_itsm")
    parser.add_argument("--postgres-db", default="sbs_itsm")
    parser.add_argument("--postgres-host", default="postgres")
    parser.add_argument("--redis-host", default="redis")
    parser.add_argument("--with-bootstrap-password", action="store_true")
    parser.add_argument(
        "--ensure-backup-encryption-key",
        action="store_true",
        help="add only the backup encryption key when upgrading an existing secret directory",
    )
    parser.add_argument(
        "--normalize-existing",
        action="store_true",
        help="normalize existing text secrets to one trailing LF without changing their values",
    )
    parser.add_argument(
        "--ensure-additive-secrets",
        action="store_true",
        help=(
            "add missing independently rotatable secrets introduced by later releases "
            "without changing existing credentials"
        ),
    )
    args = parser.parse_args()

    directory = args.directory.resolve()
    if args.normalize_existing:
        return _normalize_existing_secrets(directory)
    if args.ensure_additive_secrets:
        return _ensure_additive_secrets(directory)
    if args.ensure_backup_encryption_key:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "backup_encryption_key"
        if path.exists():
            print(f"Backup encryption key already exists in {directory}")
            return 0
        _write_secret(directory, "backup_encryption_key", _random_secret(48))
        print(f"Created backup encryption key in {directory}")
        return 0

    directory.mkdir(parents=True, exist_ok=True)
    postgres_password = _random_secret()
    redis_password = _random_secret()
    values = {
        "backup_encryption_key": _random_secret(48),
        "jwt_secret_key": _random_secret(48),
        "mfa_encryption_key": _random_secret(48),
        "credential_encryption_key": _random_secret(48),
        "configuration_package_signing_key": _random_secret(48),
        "metrics_auth_token": _random_secret(36),
        "alertmanager_webhook_token": _random_secret(36),
        "postgres_password": postgres_password,
        "redis_password": redis_password,
        "database_url": (
            "postgresql+psycopg://"
            f"{quote(args.postgres_user, safe='')}:{quote(postgres_password, safe='')}"
            f"@{args.postgres_host}:5432/{quote(args.postgres_db, safe='')}"
        ),
        "redis_url": f"redis://:{quote(redis_password, safe='')}@{args.redis_host}:6379/0",
        "grafana_admin_password": _random_secret(30),
        # Replace this disabled value with the secret issued by the OIDC provider
        # before setting OIDC_ENABLED=true.
        "oidc_client_secret": "disabled-" + _random_secret(24),
        # Optional direct alert channels remain fail-closed until an operator
        # replaces the relevant disabled value and configures its non-secret
        # SMTP metadata in .env.production.
        "jobs_alert_smtp_password": "disabled-" + _random_secret(24),
        "jobs_alert_slack_webhook_url": "disabled-" + _random_secret(24),
        "jobs_alert_pagerduty_routing_key": "disabled-" + _random_secret(24),
        "jobs_alert_webhook_url": "disabled-" + _random_secret(24),
    }
    if args.with_bootstrap_password:
        values["bootstrap_root_password"] = _random_secret(30) + "!9a"

    conflicts = [directory / name for name in values if (directory / name).exists()]
    if conflicts:
        print(f"[FAIL] refusing to overwrite existing secret: {conflicts[0]}", file=sys.stderr)
        return 1
    for name, value in values.items():
        _write_secret(directory, name, value)

    print(f"Created {len(values)} production secret files in {directory}")
    print("Keep this directory outside version control and back it up in an approved secret manager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
