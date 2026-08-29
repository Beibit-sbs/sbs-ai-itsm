from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _load_script(filename: str):
    path = REPOSITORY_ROOT / "scripts" / filename
    module_name = "test_" + filename.removesuffix(".py").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_secret_writer_uses_linux_line_endings_on_every_host(tmp_path) -> None:
    generator = _load_script("init-production-secrets.py")

    generator._write_secret(tmp_path, "test_secret", "opaque-value")

    assert (tmp_path / "test_secret").read_bytes() == b"opaque-value\n"


def test_existing_secret_normalization_preserves_value(tmp_path) -> None:
    generator = _load_script("init-production-secrets.py")
    secret = tmp_path / "redis_password"
    secret.write_bytes(b"opaque-value\r\n")

    assert generator._normalize_existing_secrets(tmp_path) == 0
    assert secret.read_bytes() == b"opaque-value\n"


def test_additive_secret_upgrade_preserves_existing_values(tmp_path) -> None:
    generator = _load_script("init-production-secrets.py")
    existing = tmp_path / "credential_encryption_key"
    existing.write_bytes(b"existing-credential-key\n")

    assert generator._ensure_additive_secrets(tmp_path) == 0
    assert existing.read_bytes() == b"existing-credential-key\n"
    assert (tmp_path / "configuration_package_signing_key").is_file()
    assert (tmp_path / "jobs_alert_smtp_password").read_text(
        encoding="utf-8"
    ).startswith("disabled-")
    assert (tmp_path / "smoke_user_password").read_text(
        encoding="utf-8"
    ).startswith("S9!")
    assert (tmp_path / "smoke_user_secondary_password").read_text(
        encoding="utf-8"
    ).startswith("S9!")
    assert (tmp_path / "performance_user_password").read_text(
        encoding="utf-8"
    ).startswith("S9!")

    before = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    assert generator._ensure_additive_secrets(tmp_path) == 0
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    } == before


def test_production_compose_keeps_staging_env_and_bootstrap_scoped() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert compose.count("${APP_ENV_FILE:-.env.production}") == 5
    assert compose.count('BOOTSTRAP_ROOT_EMAIL: ""') == 4
    assert "http://127.0.0.1:8080/" in compose
    assert "http://localhost:8080/" not in compose
    frontend = compose.split("  frontend:", 1)[1].split("  prometheus:", 1)[0]
    backend = compose.split("  backend:", 1)[1].split("  worker:", 1)[0]
    worker = compose.split("  worker:", 1)[1].split("  scheduler:", 1)[0]
    scheduler = compose.split("  scheduler:", 1)[1].split("  frontend:", 1)[0]
    assert "scale: ${BACKEND_REPLICAS:-3}" in backend
    assert 'JOBS_PERIODIC_CYCLES_ENABLED: "false"' in worker
    assert '["python", "-m", "app.workers.scheduler_worker"]' in scheduler
    assert 'JOBS_PERIODIC_CYCLES_ENABLED: "true"' in scheduler
    assert "SCHEDULER_LEASE_SECONDS" in scheduler
    assert "read_only: true" in scheduler
    assert "- ALL" in scheduler
    assert "read_only: true" in frontend
    assert "- /etc/nginx/conf.d:uid=101,gid=101,mode=0770" in frontend


def test_production_example_budgets_database_connections_for_all_replicas() -> None:
    env = {}
    for raw_line in (REPOSITORY_ROOT / ".env.production.example").read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value

    total = int(env["BACKEND_REPLICAS"]) * (
        int(env["BACKEND_DATABASE_POOL_SIZE"])
        + int(env["BACKEND_DATABASE_MAX_OVERFLOW"])
    ) + int(env["WORKER_DATABASE_POOL_SIZE"]) + int(
        env["WORKER_DATABASE_MAX_OVERFLOW"]
    ) + int(env["SCHEDULER_DATABASE_POOL_SIZE"]) + int(
        env["SCHEDULER_DATABASE_MAX_OVERFLOW"]
    )

    assert int(env["BACKEND_REPLICAS"]) >= 2
    assert 1 <= int(env["BACKEND_DATABASE_POOL_TIMEOUT_SECONDS"]) <= 3
    assert total <= 90


def test_frontend_docker_context_excludes_local_dependencies() -> None:
    dockerignore = (REPOSITORY_ROOT / "frontend" / ".dockerignore").read_text(
        encoding="utf-8"
    )

    assert "node_modules" in dockerignore.splitlines()
    assert "dist" in dockerignore.splitlines()


def test_windows_local_launcher_uses_persistent_database_and_api_proxy() -> None:
    backend_launcher = (
        REPOSITORY_ROOT / "scripts" / "start-local-backend.cmd"
    ).read_text(encoding="utf-8")
    vite_config = (
        REPOSITORY_ROOT / "frontend" / "vite.config.ts"
    ).read_text(encoding="utf-8")

    assert "sqlite:///%LOCALAPPDATA:\\=/%/Temp/sbs-ai-itsm-visible.db" in backend_launcher
    assert "%DEMO_DB_PATH%" not in backend_launcher
    assert 'set "SEED_DEMO_CATALOG=true"' in backend_launcher
    assert "'/api'" in vite_config
    assert "http://127.0.0.1:8000" in vite_config


def test_postgres_snapshot_helpers_are_project_scoped(tmp_path, monkeypatch) -> None:
    snapshot = _load_script("postgres-snapshot.py")
    env_file = tmp_path / ".env.rehearsal.local"
    env_file.write_text(
        "POSTGRES_USER=sbs_itsm\nPOSTGRES_DB=sbs_itsm\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "snapshot.dump"
    artifact.write_bytes(b"database-snapshot")
    monkeypatch.setattr(snapshot.shutil, "which", lambda _: "docker")

    assert snapshot.load_env(env_file) == {
        "POSTGRES_USER": "sbs_itsm",
        "POSTGRES_DB": "sbs_itsm",
    }
    command = snapshot.compose_base(
        project_name="sbs-itsm-rehearsal",
        compose_file=REPOSITORY_ROOT / "docker-compose.prod.yml",
        env_file=env_file,
    )
    assert command[:4] == ["docker", "compose", "--project-name", "sbs-itsm-rehearsal"]
    assert snapshot.sha256_file(artifact) == (
        "8e06b5b676678e68ccfc5d75932c0640ab680d3c979b1f9b32fd2d01febf6e4c"
    )


def test_migration_rehearsal_fixture_is_tenant_balanced() -> None:
    fixture = (
        REPOSITORY_ROOT / "scripts" / "sql" / "migration-rehearsal-fixture.sql"
    ).read_text(encoding="utf-8")

    assert "Migration Tenant A" in fixture
    assert "Migration Tenant B" in fixture
    assert fixture.count("generate_series(1, 25)") == 2
    assert "ON CONFLICT (id) DO NOTHING" in fixture


def test_production_smoke_supports_public_host_over_loopback() -> None:
    smoke = _load_script("smoke-production.py")

    client = smoke.SmokeClient(
        "http://127.0.0.1:18080",
        1,
        host_header="itsm.rehearsal.local",
    )

    assert client.default_headers == {"Host": "itsm.rehearsal.local"}


def test_resilience_harness_targets_an_explicit_compose_project(monkeypatch) -> None:
    resilience = _load_script("run_resilience_acceptance.py")
    captured = {}

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(resilience.subprocess, "run", fake_run)
    resilience._compose(
        REPOSITORY_ROOT / "docker-compose.prod.yml",
        REPOSITORY_ROOT / ".env.production.example",
        "explicit-rehearsal",
        "stop",
        "redis",
    )

    command = captured["command"]
    assert command[command.index("--project-name") + 1] == "explicit-rehearsal"
    assert command[-2:] == ["stop", "redis"]


def test_backup_encryption_round_trip_and_tamper_detection(tmp_path) -> None:
    crypto = _load_script("backup_crypto.py")
    key_file = tmp_path / "backup_encryption_key"
    key_file.write_text("x" * 48 + "\n", encoding="utf-8")
    source = tmp_path / "source.dump"
    source.write_bytes((b"production-like-database-records\n" * 1000))
    encrypted = tmp_path / "source.dump.enc"
    restored = tmp_path / "restored.dump"

    key = crypto.load_backup_key(key_file)
    crypto.encrypt_file(source, encrypted, key)
    crypto.decrypt_file(encrypted, restored, key)

    assert restored.read_bytes() == source.read_bytes()
    assert encrypted.read_bytes()[:8] == crypto.MAGIC
    tampered = bytearray(encrypted.read_bytes())
    tampered[-1] ^= 1
    encrypted.write_bytes(tampered)
    try:
        crypto.decrypt_file(encrypted, tmp_path / "tampered.dump", key)
    except Exception:
        pass
    else:
        raise AssertionError("tampered encrypted backup was accepted")


def test_runtime_data_backup_round_trip_uses_manifest(tmp_path) -> None:
    runtime = _load_script("runtime-data-backup.py")
    repository = tmp_path / "repository"
    upload = repository / "backend" / "uploads"
    upload.mkdir(parents=True)
    attachment = upload / "ticket-evidence.txt"
    attachment.write_text("attachment restore proof", encoding="utf-8")
    key_file = tmp_path / "backup_encryption_key"
    key_file.write_text("k" * 48 + "\n", encoding="utf-8")
    archive = tmp_path / "runtime-data.tar.gz.enc"

    manifest = runtime.create_archive(
        root=repository,
        sources=[Path("backend/uploads")],
        archive=archive,
        encryption_key_file=key_file,
    )
    target = tmp_path / "restored"
    result = runtime.restore_archive(
        archive=archive,
        target_root=target,
        encryption_key_file=key_file,
        confirm_restore=True,
    )

    assert manifest["encrypted"] is True
    assert manifest["file_count"] == 1
    assert result["file_count"] == 1
    assert (
        target / "backend" / "uploads" / "ticket-evidence.txt"
    ).read_text(encoding="utf-8") == "attachment restore proof"


def test_backup_retention_is_dry_run_and_keeps_newest(tmp_path) -> None:
    retention = _load_script("backup-retention.py")
    artifacts = []
    for index in range(4):
        artifact = tmp_path / f"backup-{index}.dump.enc"
        artifact.write_bytes(b"encrypted")
        os.utime(artifact, (1_700_000_000 + index * 86_400,) * 2)
        artifacts.append(artifact)

    keep, expired = retention.retention_plan(
        artifacts,
        daily=2,
        weekly=0,
        monthly=0,
    )

    assert artifacts[-1] in keep
    assert artifacts[-2] in keep
    assert artifacts[0] in expired


def test_retention_streams_are_grouped_by_artifact_directory(tmp_path) -> None:
    retention = _load_script("backup-retention.py")
    database = tmp_path / "database"
    data = tmp_path / "data"
    database.mkdir()
    data.mkdir()
    db_artifact = database / "database.dump.enc"
    data_artifact = data / "runtime.tar.gz.enc"
    db_artifact.write_bytes(b"db")
    data_artifact.write_bytes(b"data")

    db_keep, _ = retention.retention_plan(
        [db_artifact], daily=1, weekly=0, monthly=0
    )
    data_keep, _ = retention.retention_plan(
        [data_artifact], daily=1, weekly=0, monthly=0
    )

    assert db_artifact in db_keep
    assert data_artifact in data_keep


def test_backup_alertmanager_payload_is_actionable(monkeypatch) -> None:
    snapshot = _load_script("postgres-snapshot.py")
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        captured["payload"] = http_request.data
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(snapshot.request, "urlopen", fake_urlopen)
    snapshot.submit_alertmanager_status(
        base_url="http://127.0.0.1:19093",
        project_name="sbs-itsm-rehearsal",
        status="firing",
        starts_at="2026-07-28T10:00:00+00:00",
        detail="pg_dump failed",
    )

    payload = __import__("json").loads(captured["payload"])
    assert captured["url"].endswith("/api/v2/alerts")
    assert payload[0]["labels"]["alertname"] == "SbsDatabaseBackupFailed"
    assert payload[0]["labels"]["severity"] == "critical"
    assert payload[0]["annotations"]["runbook"].endswith(
        "BACKUP-RESTORE-RUNBOOK.md"
    )
