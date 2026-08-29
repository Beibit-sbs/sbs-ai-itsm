from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_workload_profiles_have_bounded_acceptance_thresholds() -> None:
    contract = json.loads(
        (ROOT / "performance" / "workload-profile.json").read_text(
            encoding="utf-8"
        )
    )

    assert set(contract["profiles"]) == {"baseline", "peak", "soak"}
    for profile in contract["profiles"].values():
        assert 0 < profile["concurrency"] <= 100
        assert 0 < profile["duration_seconds"] <= 7200
        assert 0 <= profile["write_percent"] <= 10
        assert profile["thresholds"]["http_error_percent_max"] <= 1
        assert profile["thresholds"]["http_p95_ms_max"] <= 1000
        assert profile["thresholds"]["http_p99_ms_max"] <= 2000


def test_security_catalog_has_release_blocking_coverage() -> None:
    catalog = json.loads(
        (ROOT / "security" / "acceptance-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    control_types = {item["type"] for item in catalog["controls"]}

    assert set(catalog["release_blocking_severities"]) == {"CRITICAL", "HIGH"}
    assert {
        "SCA",
        "SAST",
        "IMAGE",
        "SECRET",
        "ABUSE",
        "ISOLATION",
        "AUTHORIZATION",
        "DAST",
    } <= control_types
    assert any(
        item["id"] == "SEC-PRIVILEGE-DELEGATION"
        for item in catalog["controls"]
    )
    assert {
        "SEC-SYSTEM-ROLE-INTEGRITY",
        "SEC-TENANT-ADMIN-CONTINUITY",
        "SEC-ROUTE-AUTHENTICATION-CONTRACT",
    } <= {item["id"] for item in catalog["controls"]}
    assert all(item["owner"] and item["acceptance"] for item in catalog["controls"])


def test_proxy_and_application_have_layered_abuse_limits() -> None:
    nginx = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    middleware = (
        ROOT / "backend" / "app" / "core" / "middleware.py"
    ).read_text(encoding="utf-8")

    assert "client_max_body_size 6m" in nginx
    assert "limit_req zone=sbs_api_per_ip" in nginx
    assert "limit_conn sbs_connections_per_ip" in nginx
    assert "class RequestBodyLimitMiddleware" in middleware
    assert "REQUEST_BODY_TOO_LARGE" in middleware


def test_ci_blocks_on_security_findings_and_staging_dast_is_governed() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    dast = (
        ROOT / ".github" / "workflows" / "staging-dast.yml"
    ).read_text(encoding="utf-8")

    for gate in (
        "pip-audit",
        "bandit -r app",
        "npm audit",
        "anchore/scan-action@v7",
        "gitleaks",
    ):
        assert gate in ci
    assert "environment: staging-security" in dast
    assert "STAGING_DAST_URL" in dast
    assert "zaproxy/action-baseline@v0.15.0" in dast


def test_compose_bounds_resources_logs_and_redis_memory() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "x-logging: &default-logging" in compose
    assert compose.count("logging: *default-logging") >= 8
    assert compose.count("resources:") >= 7
    assert "--maxmemory-policy noeviction" in compose
    assert "REDIS_MAXMEMORY" in compose
