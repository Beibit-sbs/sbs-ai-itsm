#!/usr/bin/env python3
"""Fail-fast smoke checks for a deployed SBS AI ITSM instance."""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _load_secret(env_file: Path, name: str) -> str:
    secrets_dir = os.environ.get("SECRETS_DIR", "")
    if secrets_dir:
        directory = Path(secrets_dir)
        if not directory.is_absolute():
            directory = env_file.resolve().parent / directory
        path = directory / name
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return os.environ.get(name.upper(), "")


class SmokeClient:
    def __init__(
        self,
        base_url: str,
        timeout: float,
        *,
        host_header: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        normalized_host = (host_header or "").strip()
        if normalized_host and any(
            character.isspace() or character in "/\\"
            for character in normalized_host
        ):
            raise RuntimeError("host header contains invalid characters")
        self.default_headers = {"Host": normalized_host} if normalized_host else {}
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(
        self,
        method: str,
        path: str,
        *,
        expected: set[int],
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        body = json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Accept": "application/json", "User-Agent": "sbs-production-smoke/1.0"}
        request_headers.update(self.default_headers)
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = Request(
            urljoin(self.base_url, path.lstrip("/")),
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status_code = response.status
                response_body = response.read()
                response_headers = dict(response.headers.items())
        except HTTPError as exc:
            status_code = exc.code
            response_body = exc.read()
            response_headers = dict(exc.headers.items())
        except URLError as exc:
            raise RuntimeError(f"{method} {path} is unreachable: {exc.reason}") from exc
        if status_code not in expected:
            preview = response_body.decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"{method} {path} returned {status_code}; expected {sorted(expected)}: {preview}")
        return status_code, response_body, response_headers


def _json(body: bytes, path: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} did not return a JSON object")
    return value


def run(
    client: SmokeClient,
    *,
    env_file: Path,
    grafana_url: str | None,
    alertmanager_url: str | None,
) -> None:
    _, body, _ = client.request("GET", "/api/v1/health/liveness", expected={200})
    if _json(body, "liveness").get("status") != "alive":
        raise RuntimeError("liveness payload is not alive")
    print("[OK] liveness")

    _, body, _ = client.request("GET", "/api/v1/health/readiness", expected={200})
    readiness = _json(body, "readiness")
    if readiness.get("ready") is not True:
        raise RuntimeError(f"readiness payload is not ready: {readiness.get('checks')}")
    print("[OK] readiness (database, Redis, migrations, runtime)")

    _, body, headers = client.request("GET", "/", expected={200})
    content_type = headers.get("Content-Type", headers.get("content-type", ""))
    if "text/html" not in content_type or b"<html" not in body.lower():
        raise RuntimeError("frontend root did not return HTML")
    print("[OK] frontend")

    client.request("GET", "/api/v1/tickets", expected={401})
    print("[OK] protected API rejects anonymous access")

    metrics_token = _load_secret(env_file, "metrics_auth_token")
    if not metrics_token:
        raise RuntimeError("METRICS_AUTH_TOKEN is required for production smoke checks")
    client.request("GET", "/api/v1/metrics", expected={401})
    _, body, _ = client.request(
        "GET",
        "/api/v1/metrics",
        expected={200},
        headers={"Authorization": f"Bearer {metrics_token}"},
    )
    if b"sbs_http_requests_total" not in body:
        raise RuntimeError("metrics endpoint did not return SBS Prometheus metrics")
    print("[OK] authenticated metrics")

    if grafana_url:
        grafana = SmokeClient(grafana_url, client.timeout)
        _, body, _ = grafana.request("GET", "/api/health", expected={200})
        if _json(body, "Grafana health").get("database") != "ok":
            raise RuntimeError("Grafana database health is not ok")
        print("[OK] Grafana")

    if alertmanager_url:
        alertmanager = SmokeClient(alertmanager_url, client.timeout)
        _, body, _ = alertmanager.request("GET", "/-/ready", expected={200})
        normalized_body = body.strip().lower()
        if normalized_body not in {b"ok", b"ready"} and b"ready" not in normalized_body:
            raise RuntimeError("Alertmanager readiness response is invalid")
        print("[OK] Alertmanager")

    smoke_email = os.environ.get("SMOKE_EMAIL", "")
    smoke_password = os.environ.get("SMOKE_PASSWORD", "") or _load_secret(
        env_file,
        "smoke_user_password",
    )
    if bool(smoke_email) != bool(smoke_password):
        raise RuntimeError("SMOKE_EMAIL and SMOKE_PASSWORD must be configured together")
    if not smoke_email:
        print("[SKIP] authenticated journey (dedicated SMOKE_EMAIL/SMOKE_PASSWORD not configured)")
        return

    _, body, _ = client.request(
        "POST",
        "/api/v1/auth/login",
        expected={200},
        payload={"email": smoke_email, "password": smoke_password},
    )
    access_token = str(_json(body, "login").get("access_token") or "")
    if not access_token:
        raise RuntimeError("login response has no access token")
    auth_headers = {"Authorization": f"Bearer {access_token}"}
    _, body, _ = client.request("GET", "/api/v1/auth/me", expected={200}, headers=auth_headers)
    if str(_json(body, "auth/me").get("email", "")).lower() != smoke_email.lower():
        raise RuntimeError("authenticated identity does not match SMOKE_EMAIL")
    client.request("POST", "/api/v1/auth/logout", expected={200}, payload={}, headers=auth_headers)
    print("[OK] login, identity and logout")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env.production"))
    parser.add_argument("--base-url", default=None, help="Public frontend URL; defaults to SMOKE_BASE_URL")
    parser.add_argument(
        "--host-header",
        default=None,
        help=(
            "Public Host header when connecting through a loopback address; "
            "defaults to SMOKE_HOST_HEADER"
        ),
    )
    parser.add_argument("--grafana-url", default=None, help="Grafana URL; defaults to local production port")
    parser.add_argument(
        "--alertmanager-url",
        default=None,
        help="Alertmanager URL; defaults to local production port",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    _load_env(args.env_file)
    default_port = os.environ.get("FRONTEND_PORT", "80")
    base_url = args.base_url or os.environ.get("SMOKE_BASE_URL") or f"http://127.0.0.1:{default_port}"
    grafana_url = (
        args.grafana_url
        or os.environ.get("GRAFANA_SMOKE_URL")
        or f"http://127.0.0.1:{os.environ.get('GRAFANA_PORT', '3000')}"
    )
    alertmanager_url = (
        args.alertmanager_url
        or os.environ.get("ALERTMANAGER_SMOKE_URL")
        or f"http://127.0.0.1:{os.environ.get('ALERTMANAGER_PORT', '9093')}"
    )
    try:
        run(
            SmokeClient(
                base_url,
                args.timeout,
                host_header=args.host_header or os.environ.get("SMOKE_HOST_HEADER"),
            ),
            env_file=args.env_file,
            grafana_url=grafana_url,
            alertmanager_url=alertmanager_url,
        )
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    print("Production smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
