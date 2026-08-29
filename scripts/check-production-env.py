#!/usr/bin/env python3
"""Cross-platform production configuration preflight without secret disclosure."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit


PLACEHOLDER_MARKERS = ("CHANGE-ME", "CHANGEME", "DISABLED-", "GENERATE-", "REPLACE")
INLINE_SECRET_KEYS = (
    "JWT_SECRET_KEY",
    "MFA_ENCRYPTION_KEY",
    "CONFIGURATION_PACKAGE_SIGNING_KEY",
    "METRICS_AUTH_TOKEN",
    "ALERTMANAGER_WEBHOOK_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "BOOTSTRAP_ROOT_PASSWORD",
    "OIDC_CLIENT_SECRET",
    "JOBS_ALERT_SMTP_PASSWORD",
    "JOBS_ALERT_SLACK_WEBHOOK_URL",
    "JOBS_ALERT_PAGERDUTY_ROUTING_KEY",
    "JOBS_ALERT_WEBHOOK_URL",
    "BACKUP_ENCRYPTION_KEY",
)
REQUIRED_ENV_KEYS = (
    "APP_ENV",
    "APP_ENV_FILE",
    "API_V1_PREFIX",
    "BACKEND_CORS_ORIGINS",
    "TRUSTED_HOSTS",
    "FORWARDED_ALLOW_IPS",
    "EDGE_SUBNET",
    "EDGE_GATEWAY",
    "FRONTEND_EDGE_IP",
    "TLS_PROXY_CIDR",
    "API_RATE_LIMIT",
    "API_BURST",
    "API_CONNECTION_LIMIT",
    "LOGIN_RATE_LIMIT",
    "LOGIN_RATE_BURST",
    "BACKEND_DATABASE_POOL_SIZE",
    "BACKEND_DATABASE_MAX_OVERFLOW",
    "BACKEND_DATABASE_POOL_TIMEOUT_SECONDS",
    "BACKEND_REPLICAS",
    "WORKER_DATABASE_POOL_SIZE",
    "WORKER_DATABASE_MAX_OVERFLOW",
    "WORKER_DATABASE_POOL_TIMEOUT_SECONDS",
    "EMAIL_ATTACHMENT_MANUAL_RELEASE_WITHOUT_CLEAN_SCAN",
    "EMAIL_ATTACHMENT_DOWNLOAD_TOKEN_TTL_SECONDS",
    "SECRETS_DIR",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "DEMO_MODE",
    "SEED_DEMO_CATALOG",
    "RUN_STARTUP_DDL",
    "DASHBOARD_REALTIME_TRANSPORT",
    "MFA_ENFORCEMENT_ENABLED",
    "MFA_REQUIRED_ROLE_CODES",
    "PROMETHEUS_URL",
    "PROMETHEUS_TIMEOUT_SECONDS",
    "CLOUDWATCH_REGION",
    "CLOUDWATCH_NAMESPACE",
)
REQUIRED_SECRET_LENGTHS = {
    "backup_encryption_key": 32,
    "jwt_secret_key": 32,
    "mfa_encryption_key": 32,
    "credential_encryption_key": 32,
    "configuration_package_signing_key": 32,
    "metrics_auth_token": 24,
    "alertmanager_webhook_token": 24,
    "postgres_password": 16,
    "redis_password": 16,
    "database_url": 32,
    "redis_url": 24,
    "grafana_admin_password": 16,
}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_placeholder(value: str) -> bool:
    normalized = value.strip().upper()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def resolve_from_root(root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (root / candidate).resolve()


@dataclass
class CheckResult:
    ok: int = 0
    warnings: int = 0
    failures: int = 0

    def mark(self, level: str, name: str, detail: str) -> None:
        if level == "OK":
            self.ok += 1
        elif level == "WARN":
            self.warnings += 1
        else:
            self.failures += 1
        print(f"[{level}] {name}: {detail}")

    def success(self, name: str, detail: str) -> None:
        self.mark("OK", name, detail)

    def warn(self, name: str, detail: str) -> None:
        self.mark("WARN", name, detail)

    def fail(self, name: str, detail: str) -> None:
        self.mark("FAIL", name, detail)


def read_secret(secrets_dir: Path, name: str) -> str:
    path = secrets_dir / name
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def check_secret(
    result: CheckResult,
    secrets_dir: Path,
    name: str,
    minimum_length: int,
) -> str:
    value = read_secret(secrets_dir, name)
    if not value:
        result.fail(f"secret:{name}", "missing or empty")
    elif is_placeholder(value):
        result.fail(f"secret:{name}", "placeholder value")
    elif len(value) < minimum_length:
        result.fail(f"secret:{name}", f"must contain at least {minimum_length} characters")
    else:
        result.success(f"secret:{name}", "present and non-placeholder")
    return value


def check_url_credentials(
    result: CheckResult,
    *,
    name: str,
    value: str,
    allowed_schemes: set[str],
    require_username: bool = True,
) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        result.fail(name, f"expected URL scheme: {', '.join(sorted(allowed_schemes))}")
    elif (
        (require_username and not parsed.username)
        or not parsed.password
        or len(parsed.password) < 16
    ):
        result.fail(name, "authenticated URL with password of at least 16 characters required")
    elif is_placeholder(parsed.password):
        result.fail(name, "URL contains a placeholder credential")
    else:
        result.success(name, "authenticated URL format accepted")


def check_service_url(
    result: CheckResult,
    *,
    name: str,
    value: str,
) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        result.fail(
            name,
            "explicit HTTP(S) URL without credentials, query, or fragment required",
        )
    else:
        result.success(name, "bounded service URL format accepted")


def is_approved_https_destination(
    value: str,
    *,
    allowed_hosts: set[str] | None = None,
) -> bool:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return bool(
        parsed.scheme == "https"
        and hostname
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and port in {None, 443}
        and (allowed_hosts is None or hostname in allowed_hosts)
    )


def run_compose_validation(
    result: CheckResult,
    *,
    root: Path,
    env_file: Path,
) -> None:
    docker = shutil.which("docker")
    if not docker:
        result.fail("production compose", "Docker CLI is not installed")
        return
    command = [
        docker,
        "compose",
        "-f",
        str(root / "docker-compose.prod.yml"),
        "--env-file",
        str(env_file),
        "config",
        "--quiet",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode == 0:
        result.success("production compose", "configuration is valid")
    else:
        safe_error = (completed.stderr or completed.stdout).strip().splitlines()
        detail = safe_error[-1][:240] if safe_error else "configuration is invalid"
        result.fail("production compose", detail)


def run_preflight(root: Path, env_file: Path, *, validate_compose: bool = True) -> CheckResult:
    result = CheckResult()
    if not env_file.is_file():
        result.fail("environment file", "file not found")
        return result
    result.success("environment file", "exists")
    values = load_env(env_file)

    configured_env_file = values.get("APP_ENV_FILE", "")
    configured_env_path = (
        resolve_from_root(root, configured_env_file)
        if configured_env_file
        else root / "__missing__"
    )
    if configured_env_path == env_file.resolve():
        result.success("APP_ENV_FILE target", "matches the validated environment file")
    else:
        result.fail(
            "APP_ENV_FILE target",
            "must point to the same environment file passed to preflight",
        )

    try:
        ignored = (
            subprocess.run(
                ["git", "-C", str(root), "check-ignore", "-q", str(env_file)],
                check=False,
                timeout=10,
            ).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        ignored = False
    if ignored:
        result.success("environment git ignore", "ignored")
    else:
        result.fail("environment git ignore", "file must be ignored by git")

    for key in REQUIRED_ENV_KEYS:
        if values.get(key, ""):
            result.success(key, "set")
        else:
            result.fail(key, "not set")

    inline_keys = [key for key in INLINE_SECRET_KEYS if values.get(key, "")]
    if inline_keys:
        for key in inline_keys:
            result.fail(key, "inline secret detected; move it to SECRETS_DIR")
    else:
        result.success("inline secrets", "none detected")

    secrets_value = values.get("SECRETS_DIR", "")
    secrets_dir = resolve_from_root(root, secrets_value) if secrets_value else root / "__missing__"
    if "secrets.example" in secrets_value.replace("\\", "/"):
        result.fail("SECRETS_DIR", "example secrets cannot be used")
    elif secrets_dir.is_dir():
        result.success("SECRETS_DIR", "secret directory exists")
    else:
        result.fail("SECRETS_DIR", "secret directory does not exist")
    try:
        secrets_ignored = (
            subprocess.run(
                ["git", "-C", str(root), "check-ignore", "-q", str(secrets_dir)],
                check=False,
                timeout=10,
            ).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        secrets_ignored = False
    if secrets_ignored:
        result.success("SECRETS_DIR git ignore", "ignored")
    else:
        result.fail("SECRETS_DIR git ignore", "secret directory must be ignored by git")

    secret_values = {
        name: check_secret(result, secrets_dir, name, minimum)
        for name, minimum in REQUIRED_SECRET_LENGTHS.items()
    }

    oidc_enabled = values.get("OIDC_ENABLED", "").lower() == "true"
    oidc_secret = read_secret(secrets_dir, "oidc_client_secret")
    if oidc_enabled:
        check_secret(result, secrets_dir, "oidc_client_secret", 12)
    elif oidc_secret:
        result.success("secret:oidc_client_secret", "mounted for the disabled provider")
    else:
        result.fail("secret:oidc_client_secret", "missing; required by production Compose")

    optional_alert_secret_names = (
        "jobs_alert_smtp_password",
        "jobs_alert_slack_webhook_url",
        "jobs_alert_pagerduty_routing_key",
        "jobs_alert_webhook_url",
    )
    optional_alert_secrets: dict[str, str] = {}
    for name in optional_alert_secret_names:
        secret_value = read_secret(secrets_dir, name)
        optional_alert_secrets[name] = secret_value
        if not secret_value:
            result.fail(f"secret:{name}", "missing; required by production Compose")
        elif is_placeholder(secret_value):
            result.success(f"secret:{name}", "mounted and explicitly disabled")
        else:
            result.success(f"secret:{name}", "mounted and enabled")

    bootstrap_email = values.get("BOOTSTRAP_ROOT_EMAIL", "")
    if bootstrap_email:
        check_secret(result, secrets_dir, "bootstrap_root_password", 14)
        result.warn(
            "bootstrap root",
            "remove bootstrap email and password secret after first login and rotation",
        )
    else:
        result.success("bootstrap root", "first-deploy credential disabled")

    distinct_names = (
        "backup_encryption_key",
        "jwt_secret_key",
        "mfa_encryption_key",
        "credential_encryption_key",
        "configuration_package_signing_key",
        "metrics_auth_token",
        "alertmanager_webhook_token",
        "postgres_password",
        "redis_password",
        "grafana_admin_password",
    )
    distinct_values = [read_secret(secrets_dir, name) for name in distinct_names]
    distinct_values.extend(
        value
        for value in optional_alert_secrets.values()
        if value and not is_placeholder(value)
    )
    nonempty_values = [value for value in distinct_values if value]
    if len(nonempty_values) != len(set(nonempty_values)):
        result.fail("secret separation", "two or more production credentials are identical")
    else:
        result.success("secret separation", "credentials are distinct")

    check_url_credentials(
        result,
        name="secret:database_url format",
        value=secret_values.get("database_url", ""),
        allowed_schemes={"postgresql", "postgresql+psycopg"},
    )
    check_url_credentials(
        result,
        name="secret:redis_url format",
        value=secret_values.get("redis_url", ""),
        allowed_schemes={"redis", "rediss"},
        require_username=False,
    )
    check_service_url(
        result,
        name="PROMETHEUS_URL format",
        value=values.get("PROMETHEUS_URL", ""),
    )
    try:
        prometheus_timeout = int(values.get("PROMETHEUS_TIMEOUT_SECONDS", "0"))
    except ValueError:
        prometheus_timeout = 0
    if 1 <= prometheus_timeout <= 30:
        result.success("PROMETHEUS_TIMEOUT_SECONDS bound", "1..30 seconds")
    else:
        result.fail(
            "PROMETHEUS_TIMEOUT_SECONDS bound",
            "must be an integer from 1 through 30",
        )

    active_alert_channels: list[str] = []
    smtp_host = values.get("JOBS_ALERT_SMTP_HOST", "").strip()
    smtp_username = values.get("JOBS_ALERT_SMTP_USERNAME", "").strip()
    if smtp_host:
        smtp_from = values.get("JOBS_ALERT_SMTP_FROM_ADDRESS", "").strip()
        smtp_recipients = [
            item.strip()
            for item in values.get("JOBS_ALERT_EMAIL_RECIPIENTS", "").split(",")
            if item.strip()
        ]
        smtp_starttls = (
            values.get("JOBS_ALERT_SMTP_STARTTLS", "").strip().lower() == "true"
        )
        smtp_password = optional_alert_secrets["jobs_alert_smtp_password"]
        if (
            smtp_host.lower() in {"localhost", "127.0.0.1", "::1"}
            or not smtp_from
            or "@" not in smtp_from
            or not smtp_recipients
            or not smtp_starttls
            or (smtp_username and is_placeholder(smtp_password))
        ):
            result.fail(
                "direct SMTP alerts",
                "non-loopback host, sender, recipients, STARTTLS, and paired "
                "credential secret are required",
            )
        else:
            active_alert_channels.append("smtp")
            result.success("direct SMTP alerts", "bounded channel configuration accepted")
    elif smtp_username or values.get("JOBS_ALERT_SMTP_FROM_ADDRESS", "").strip():
        result.fail("direct SMTP alerts", "SMTP host is required")

    slack_url = optional_alert_secrets["jobs_alert_slack_webhook_url"]
    if slack_url and not is_placeholder(slack_url):
        if is_approved_https_destination(
            slack_url,
            allowed_hosts={"hooks.slack.com", "hooks.slack-gov.com"},
        ):
            active_alert_channels.append("slack")
            result.success("direct Slack alerts", "approved HTTPS destination")
        else:
            result.fail("direct Slack alerts", "approved Slack HTTPS webhook required")

    pagerduty_key = optional_alert_secrets["jobs_alert_pagerduty_routing_key"]
    if pagerduty_key and not is_placeholder(pagerduty_key):
        if len(pagerduty_key) >= 20:
            active_alert_channels.append("pagerduty")
            result.success("direct PagerDuty alerts", "routing key is configured")
        else:
            result.fail("direct PagerDuty alerts", "routing key is too short")

    webhook_url = optional_alert_secrets["jobs_alert_webhook_url"]
    if webhook_url and not is_placeholder(webhook_url):
        if is_approved_https_destination(webhook_url):
            active_alert_channels.append("webhook")
            result.success("direct webhook alerts", "deployment-fixed HTTPS destination")
        else:
            result.fail("direct webhook alerts", "explicit HTTPS destination required")

    try:
        alert_timeout = int(values.get("JOBS_ALERT_TIMEOUT_SECONDS", "0"))
    except ValueError:
        alert_timeout = 0
    if 1 <= alert_timeout <= 30:
        result.success("JOBS_ALERT_TIMEOUT_SECONDS bound", "1..30 seconds")
    else:
        result.fail(
            "JOBS_ALERT_TIMEOUT_SECONDS bound",
            "must be an integer from 1 through 30",
        )
    if active_alert_channels:
        result.success(
            "direct alert delivery",
            f"{len(active_alert_channels)} channel(s) explicitly configured",
        )
    else:
        result.warn(
            "direct alert delivery",
            "disabled; Alertmanager event-to-incident routing remains primary",
        )

    safety_expectations = {
        "APP_ENV": "production",
        "DEMO_MODE": "false",
        "SEED_DEMO_CATALOG": "false",
        "RUN_STARTUP_DDL": "false",
        "DASHBOARD_REALTIME_TRANSPORT": "redis",
    }
    for key, expected in safety_expectations.items():
        if values.get(key, "").lower() == expected:
            result.success(f"{key} safety", expected)
        else:
            result.fail(f"{key} safety", f"must be {expected}")

    origins = [item.strip() for item in values.get("BACKEND_CORS_ORIGINS", "").split(",") if item.strip()]
    invalid_origins = [
        origin
        for origin in origins
        if (
            origin == "*"
            or urlsplit(origin).scheme != "https"
            or not urlsplit(origin).hostname
            or urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}
            or urlsplit(origin).path not in {"", "/"}
        )
    ]
    if origins and not invalid_origins:
        result.success("BACKEND_CORS_ORIGINS", "explicit HTTPS origins")
    else:
        result.fail("BACKEND_CORS_ORIGINS", "must contain only explicit HTTPS origins")

    cors_hosts = {
        str(urlsplit(origin).hostname).lower()
        for origin in origins
        if urlsplit(origin).hostname
    }
    trusted_hosts = {
        item.strip().lower().rstrip(".")
        for item in values.get("TRUSTED_HOSTS", "").split(",")
        if item.strip()
    }
    if (
        trusted_hosts
        and "*" not in trusted_hosts
        and cors_hosts.issubset(trusted_hosts)
        and "backend" in trusted_hosts
    ):
        result.success("TRUSTED_HOSTS", "explicit public and internal scrape hosts")
    else:
        result.fail(
            "TRUSTED_HOSTS",
            "must include every CORS hostname and backend, without wildcards",
        )

    try:
        edge_subnet = ipaddress.ip_network(values.get("EDGE_SUBNET", ""), strict=True)
        edge_gateway = ipaddress.ip_address(values.get("EDGE_GATEWAY", ""))
        frontend_edge_ip = ipaddress.ip_address(values.get("FRONTEND_EDGE_IP", ""))
        proxy_cidr = ipaddress.ip_network(
            values.get("TLS_PROXY_CIDR", ""),
            strict=False,
        )
        forwarded_networks = [
            ipaddress.ip_network(item.strip(), strict=False)
            for item in values.get("FORWARDED_ALLOW_IPS", "").split(",")
            if item.strip() and item.strip() != "*"
        ]
        edge_valid = (
            edge_subnet.is_private
            and edge_gateway in edge_subnet
            and frontend_edge_ip in edge_subnet
            and edge_gateway != frontend_edge_ip
        )
        proxy_valid = (
            proxy_cidr.prefixlen == proxy_cidr.max_prefixlen
            and edge_gateway in proxy_cidr
        )
        forwarded_valid = (
            values.get("FORWARDED_ALLOW_IPS", "").strip() != "*"
            and len(forwarded_networks) == 1
            and forwarded_networks[0].prefixlen
            == forwarded_networks[0].max_prefixlen
            and frontend_edge_ip in forwarded_networks[0]
        )
    except ValueError:
        edge_valid = proxy_valid = forwarded_valid = False

    if edge_valid:
        result.success("edge network identity", "private subnet with distinct proxy identities")
    else:
        result.fail(
            "edge network identity",
            "EDGE_GATEWAY and FRONTEND_EDGE_IP must be distinct members of EDGE_SUBNET",
        )
    if proxy_valid:
        result.success("TLS_PROXY_CIDR", "exact edge gateway address")
    else:
        result.fail("TLS_PROXY_CIDR", "must be an exact address containing EDGE_GATEWAY")
    if forwarded_valid:
        result.success("FORWARDED_ALLOW_IPS", "exact frontend proxy address")
    else:
        result.fail(
            "FORWARDED_ALLOW_IPS",
            "must be the exact FRONTEND_EDGE_IP without wildcard trust",
        )

    rate_pattern = re.compile(r"^([1-9][0-9]*)r/s$")
    api_rate_match = rate_pattern.fullmatch(values.get("API_RATE_LIMIT", ""))
    login_rate_match = rate_pattern.fullmatch(values.get("LOGIN_RATE_LIMIT", ""))
    try:
        api_rate = int(api_rate_match.group(1)) if api_rate_match else 0
        login_rate = int(login_rate_match.group(1)) if login_rate_match else 0
        api_burst = int(values.get("API_BURST", "0"))
        connection_limit = int(values.get("API_CONNECTION_LIMIT", "0"))
        login_burst = int(values.get("LOGIN_RATE_BURST", "0"))
        edge_limits_valid = (
            1 <= login_rate <= api_rate <= 10_000
            and 1 <= login_burst <= api_burst <= 100_000
            and 1 <= connection_limit <= 10_000
        )
    except ValueError:
        edge_limits_valid = False
    if edge_limits_valid:
        result.success(
            "edge traffic limits",
            "bounded API, connection, and stricter login limits",
        )
    else:
        result.fail(
            "edge traffic limits",
            "rates must use <positive>r/s; login <= API and login burst <= API burst",
        )

    try:
        backend_replicas = int(values.get("BACKEND_REPLICAS", "0"))
        backend_pool = int(values.get("BACKEND_DATABASE_POOL_SIZE", "0"))
        backend_overflow = int(
            values.get("BACKEND_DATABASE_MAX_OVERFLOW", "-1")
        )
        backend_timeout = int(
            values.get("BACKEND_DATABASE_POOL_TIMEOUT_SECONDS", "0")
        )
        worker_pool = int(values.get("WORKER_DATABASE_POOL_SIZE", "0"))
        worker_overflow = int(
            values.get("WORKER_DATABASE_MAX_OVERFLOW", "-1")
        )
        worker_timeout = int(
            values.get("WORKER_DATABASE_POOL_TIMEOUT_SECONDS", "0")
        )
        database_budget_valid = (
            1 <= backend_replicas <= 10
            and 1 <= backend_pool <= 80
            and 0 <= backend_overflow <= 40
            and 1 <= backend_timeout <= 3
            and 1 <= worker_pool <= 20
            and 0 <= worker_overflow <= 10
            and 1 <= worker_timeout <= 30
            and backend_replicas * (backend_pool + backend_overflow)
            + worker_pool
            + worker_overflow
            <= 90
        )
    except ValueError:
        database_budget_valid = False
    if database_budget_valid:
        result.success(
            "database connection budget",
            f"{backend_replicas} backend replica(s) and worker pools remain within the 90-connection PostgreSQL budget",
        )
    else:
        result.fail(
            "database connection budget",
            "replica count must be 1..10, backend checkout timeout 1..3s, and aggregate service pools no more than 90 connections",
        )

    manual_unscanned_release = values.get(
        "EMAIL_ATTACHMENT_MANUAL_RELEASE_WITHOUT_CLEAN_SCAN", ""
    ).lower()
    try:
        attachment_token_ttl = int(
            values.get("EMAIL_ATTACHMENT_DOWNLOAD_TOKEN_TTL_SECONDS", "0")
        )
    except ValueError:
        attachment_token_ttl = 0
    if manual_unscanned_release == "false" and 1 <= attachment_token_ttl <= 300:
        result.success(
            "attachment release policy",
            f"fail-closed with signed download TTL {attachment_token_ttl}s",
        )
    elif manual_unscanned_release == "true" and 1 <= attachment_token_ttl <= 300:
        result.warn(
            "attachment release policy",
            "manual release without CLEAN scan is explicitly enabled",
        )
    else:
        result.fail(
            "attachment release policy",
            "manual release must be true/false and signed download TTL 1..300s",
        )

    mfa_enforced = values.get("MFA_ENFORCEMENT_ENABLED", "").lower() == "true"
    required_roles = values.get("MFA_REQUIRED_ROLE_CODES", "")
    if mfa_enforced and required_roles:
        result.success("MFA enforcement", "enabled for configured privileged roles")
    elif mfa_enforced:
        result.fail("MFA_REQUIRED_ROLE_CODES", "required when MFA enforcement is enabled")
    else:
        result.warn(
            "MFA enforcement",
            "monitor-only; enroll privileged accounts before enabling enforcement",
        )

    if oidc_enabled:
        issuer = urlsplit(values.get("OIDC_ISSUER_URL", ""))
        redirect = urlsplit(values.get("OIDC_REDIRECT_URI", ""))
        if issuer.scheme == "https" and issuer.hostname:
            result.success("OIDC_ISSUER_URL", "HTTPS issuer")
        else:
            result.fail("OIDC_ISSUER_URL", "HTTPS issuer required")
        if redirect.scheme == "https" and redirect.hostname and redirect.path:
            result.success("OIDC_REDIRECT_URI", "HTTPS callback")
        else:
            result.fail("OIDC_REDIRECT_URI", "HTTPS callback required")
    else:
        result.success("OIDC", "disabled until provider credentials are configured")

    bind_address = values.get("FRONTEND_BIND_ADDRESS", "127.0.0.1")
    if bind_address == "127.0.0.1":
        result.success("FRONTEND_BIND_ADDRESS", "loopback-only")
    else:
        result.warn(
            "FRONTEND_BIND_ADDRESS",
            "externally bound; approved TLS edge and firewall policy required",
        )

    if validate_compose:
        run_compose_validation(result, root=root, env_file=env_file)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env.production"))
    parser.add_argument("--skip-compose", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env_file = args.env_file
    if not env_file.is_absolute():
        env_file = (root / env_file).resolve()
    result = run_preflight(root, env_file, validate_compose=not args.skip_compose)
    print(
        f"Summary: OK={result.ok} WARN={result.warnings} FAIL={result.failures}"
    )
    return 1 if result.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
