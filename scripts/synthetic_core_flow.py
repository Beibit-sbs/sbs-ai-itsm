from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str,
    timeout: float,
) -> tuple[int, dict[str, Any], float]:
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {
        "Accept": "application/json",
        "X-Request-ID": correlation_id,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    parsed = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(parsed, dict):
        parsed = {"response": parsed}
    return status, parsed, duration_ms


def _record(
    evidence: list[dict[str, Any]],
    *,
    name: str,
    status: int,
    duration_ms: float,
    expected: set[int],
) -> None:
    evidence.append(
        {
            "step": name,
            "status": status,
            "duration_ms": duration_ms,
            "passed": status in expected,
        }
    )
    if status not in expected:
        raise RuntimeError(
            f"Synthetic step {name} returned HTTP {status}; "
            f"expected {sorted(expected)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a secrets-safe SBS login and core ticket synthetic check."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080/api/v1",
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--exercise-ticket-lifecycle",
        action="store_true",
        help="Create and close a synthetic ticket. Without this flag the check is read-only.",
    )
    args = parser.parse_args()

    password = args.password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("Synthetic monitor password file is empty")

    correlation_id = f"synthetic-{uuid.uuid4()}"
    evidence: list[dict[str, Any]] = []
    started_at = datetime.now(UTC)

    login_status, login_payload, login_ms = _request(
        args.base_url,
        "auth/login",
        method="POST",
        payload={"email": args.email, "password": password},
        correlation_id=correlation_id,
        timeout=args.timeout,
    )
    _record(
        evidence,
        name="login",
        status=login_status,
        duration_ms=login_ms,
        expected={200},
    )
    token = str(login_payload.get("access_token") or "")
    if not token:
        raise RuntimeError("Login response did not include an access token")

    list_status, _, list_ms = _request(
        args.base_url,
        "tickets?page=1&page_size=1",
        token=token,
        correlation_id=correlation_id,
        timeout=args.timeout,
    )
    _record(
        evidence,
        name="ticket_list",
        status=list_status,
        duration_ms=list_ms,
        expected={200},
    )

    ticket_id: str | None = None
    if args.exercise_ticket_lifecycle:
        create_status, create_payload, create_ms = _request(
            args.base_url,
            "tickets",
            method="POST",
            token=token,
            payload={
                "title": f"[SYNTHETIC] Core flow {started_at.isoformat()}",
                "description": (
                    "Automated production synthetic transaction. "
                    f"Correlation: {correlation_id}"
                ),
                "requester_name": "SBS Synthetic Monitor",
                "requester_email": args.email,
                "department": "Platform Operations",
                "location": "Synthetic",
                "category": "SOFTWARE_INSTALL",
                "priority": "LOW",
            },
            correlation_id=correlation_id,
            timeout=args.timeout,
        )
        _record(
            evidence,
            name="ticket_create",
            status=create_status,
            duration_ms=create_ms,
            expected={201},
        )
        ticket_id = str(create_payload.get("id") or "")
        if not ticket_id:
            raise RuntimeError("Ticket create response did not include an id")

        read_status, _, read_ms = _request(
            args.base_url,
            f"tickets/{ticket_id}",
            token=token,
            correlation_id=correlation_id,
            timeout=args.timeout,
        )
        _record(
            evidence,
            name="ticket_read",
            status=read_status,
            duration_ms=read_ms,
            expected={200},
        )

        for next_status in ("assigned", "in_progress", "resolved", "closed"):
            transition_status, _, transition_ms = _request(
                args.base_url,
                f"tickets/{ticket_id}/transition",
                method="POST",
                token=token,
                payload={
                    "status": next_status,
                    "comment": (
                        "Synthetic lifecycle validation; "
                        f"correlation {correlation_id}"
                    ),
                },
                correlation_id=correlation_id,
                timeout=args.timeout,
            )
            _record(
                evidence,
                name=f"ticket_transition_{next_status}",
                status=transition_status,
                duration_ms=transition_ms,
                expected={200},
            )

    finished_at = datetime.now(UTC)
    evidence_payload = {
        "schema_version": "2026.07.1",
        "status": "PASS",
        "mode": "ticket_lifecycle" if args.exercise_ticket_lifecycle else "read_only",
        "base_url": args.base_url,
        "correlation_id": correlation_id,
        "ticket_id": ticket_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "steps": evidence,
    }
    canonical = json.dumps(
        evidence_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    evidence_payload["evidence_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    print(json.dumps(evidence_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, URLError, json.JSONDecodeError) as exc:
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
