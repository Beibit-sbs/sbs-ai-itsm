from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request
from urllib.request import urlopen


def _readiness(
    url: str,
    timeout: float = 5.0,
    host_header: str | None = None,
) -> tuple[int, dict[str, Any]]:
    request = Request(url, headers={"Host": host_header} if host_header else {})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
    payload = json.loads(raw.decode("utf-8")) if raw else {}
    return status, payload if isinstance(payload, dict) else {}


def _wait_for_status(
    url: str,
    expected: set[int],
    *,
    timeout_seconds: int,
    host_header: str | None,
) -> tuple[int, dict[str, Any], float]:
    started = time.monotonic()
    last_status = 0
    last_payload: dict[str, Any] = {}
    while time.monotonic() - started <= timeout_seconds:
        try:
            last_status, last_payload = _readiness(
                url,
                host_header=host_header,
            )
            if last_status in expected:
                return (
                    last_status,
                    last_payload,
                    round(time.monotonic() - started, 3),
                )
        except (OSError, URLError, json.JSONDecodeError):
            last_status = 0
            last_payload = {}
        time.sleep(1)
    raise RuntimeError(
        f"Readiness did not reach {sorted(expected)} within {timeout_seconds}s; "
        f"last status {last_status}"
    )


def _compose(
    compose_file: Path,
    env_file: Path,
    project_name: str,
    *arguments: str,
) -> None:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "--env-file",
            str(env_file),
            "--project-name",
            project_name,
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()[-1000:]
        raise RuntimeError(
            f"docker compose {' '.join(arguments)} failed: {stderr}"
        )


def _exercise_dependency(
    *,
    service: str,
    compose_file: Path,
    env_file: Path,
    project_name: str,
    readiness_url: str,
    host_header: str | None,
    failure_timeout: int,
    recovery_timeout: int,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    _compose(compose_file, env_file, project_name, "stop", service)
    try:
        failed_status, failed_payload, detection_seconds = _wait_for_status(
            readiness_url,
            {503},
            timeout_seconds=failure_timeout,
            host_header=host_header,
        )
    finally:
        _compose(compose_file, env_file, project_name, "start", service)
    recovered_status, recovered_payload, recovery_seconds = _wait_for_status(
        readiness_url,
        {200},
        timeout_seconds=recovery_timeout,
        host_header=host_header,
    )
    return {
        "service": service,
        "started_at": started_at.isoformat(),
        "failure_status": failed_status,
        "failure_checks": failed_payload.get("checks", {}),
        "detection_seconds": detection_seconds,
        "recovery_status": recovered_status,
        "recovery_checks": recovered_payload.get("checks", {}),
        "recovery_seconds": recovery_seconds,
        "passed": failed_status == 503 and recovered_status == 200,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run controlled local/staging PostgreSQL and Redis failure recovery."
        )
    )
    parser.add_argument(
        "--environment",
        choices=("local", "staging"),
        required=True,
    )
    parser.add_argument(
        "--confirm-controlled-failure",
        action="store_true",
        help="Required because the harness temporarily stops dependencies.",
    )
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path("docker-compose.prod.yml"),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env.production"),
    )
    parser.add_argument("--project-name", required=True)
    parser.add_argument(
        "--readiness-url",
        default="http://127.0.0.1:8080/api/v1/health/readiness",
    )
    parser.add_argument("--host-header")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--failure-timeout-seconds", type=int, default=45)
    parser.add_argument("--recovery-timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    if not args.confirm_controlled_failure:
        raise ValueError("--confirm-controlled-failure is required")
    if args.failure_timeout_seconds <= 0 or args.recovery_timeout_seconds <= 0:
        raise ValueError("Timeouts must be positive")
    if not args.compose_file.is_file() or not args.env_file.is_file():
        raise ValueError("Compose and environment files must exist")
    if not args.project_name or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_.-"
        for character in args.project_name
    ):
        raise ValueError("--project-name must be an explicit safe Compose project")

    initial_status, initial_payload, initial_seconds = _wait_for_status(
        args.readiness_url,
        {200},
        timeout_seconds=args.recovery_timeout_seconds,
        host_header=args.host_header,
    )
    scenarios = []
    for service in ("redis", "postgres"):
        scenarios.append(
            _exercise_dependency(
                service=service,
                compose_file=args.compose_file,
                env_file=args.env_file,
                project_name=args.project_name,
                readiness_url=args.readiness_url,
                host_header=args.host_header,
                failure_timeout=args.failure_timeout_seconds,
                recovery_timeout=args.recovery_timeout_seconds,
            )
        )

    result = {
        "schema_version": "2026.07.1",
        "status": (
            "PASS"
            if initial_status == 200 and all(item["passed"] for item in scenarios)
            else "FAIL"
        ),
        "environment": args.environment,
        "project_name": args.project_name,
        "readiness_url": args.readiness_url,
        "initial_readiness_seconds": initial_seconds,
        "initial_checks": initial_payload.get("checks", {}),
        "scenarios": scenarios,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        URLError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "2026.07.1",
                    "status": "FAIL",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc)[:500],
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(1) from exc
