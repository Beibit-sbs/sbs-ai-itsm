#!/usr/bin/env python3
"""Run a bounded lifecycle/idempotency/concurrency acceptance against a live API.

The script creates one clearly labelled non-production ticket, exercises the
canonical transition API, and leaves the ticket in CLOSED state. It never
deletes or rewrites existing records and never prints credentials or tokens.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.client import HTTPResponse
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import uuid


def _request(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "User-Agent": "sbs-gate0-lifecycle-acceptance/1.0",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=body,
        headers=headers,
        method=method,
    )
    response: HTTPResponse | HTTPError
    try:
        response = urlopen(request, timeout=timeout)  # noqa: S310 - explicit operator URL
    except HTTPError as error:
        response = error
    except URLError as error:
        raise RuntimeError(f"{method} {path} is unreachable: {error.reason}") from error
    with response:
        raw = response.read()
        status = int(response.status)
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{method} {path} returned non-JSON content") from error


def _expect(status: int, expected: set[int], label: str) -> None:
    if status not in expected:
        raise RuntimeError(f"{label}: HTTP {status}, expected {sorted(expected)}")


def _transition(
    base_url: str,
    token: str,
    ticket_id: str,
    target: str,
    version: int,
    key: str,
    *,
    timeout: float,
) -> tuple[int, Any]:
    return _request(
        base_url,
        "POST",
        f"/api/v1/tickets/{ticket_id}/transition",
        token=token,
        payload={
            "status": target,
            "expected_version": version,
            "idempotency_key": key,
        },
        timeout=timeout,
    )


def run(base_url: str, email: str, password: str, timeout: float) -> dict[str, Any]:
    status, login = _request(
        base_url,
        "POST",
        "/api/v1/auth/login",
        payload={"email": email, "password": password},
        timeout=timeout,
    )
    _expect(status, {200}, "login")
    if not isinstance(login, dict) or not login.get("access_token"):
        raise RuntimeError("login response has no access token")
    token = str(login["access_token"])

    run_id = uuid.uuid4().hex
    status, ticket = _request(
        base_url,
        "POST",
        "/api/v1/tickets",
        token=token,
        payload={
            "title": f"[Gate0 QA] lifecycle race {run_id[:8]}",
            "description": "Bounded non-production Gate 0 lifecycle acceptance.",
            "requester_name": "Gate 0 QA Requester",
            "requester_email": f"gate0-{run_id}@example.invalid",
            "on_behalf_reason": "Gate 0 live lifecycle acceptance",
            "department": "IT",
            "location": "QA",
            "category": "NETWORK_INTERNET",
            "priority": "MEDIUM",
        },
        timeout=timeout,
    )
    _expect(status, {201}, "ticket creation")
    if not isinstance(ticket, dict):
        raise RuntimeError("ticket creation response is not an object")
    ticket_id = str(ticket.get("id") or "")
    if not ticket_id or ticket.get("status") != "NEW" or ticket.get("governance_version") != 1:
        raise RuntimeError("created ticket does not expose the expected NEW/version=1 contract")
    if set(ticket.get("allowed_transitions") or []) != {"TRIAGE", "ASSIGNED", "CANCELLED"}:
        raise RuntimeError("created ticket does not expose canonical allowed transitions")

    anonymous_status, _ = _transition(
        base_url,
        "",
        ticket_id,
        "TRIAGE",
        1,
        f"gate0-anonymous-{run_id}",
        timeout=timeout,
    )
    _expect(anonymous_status, {401}, "anonymous transition denial")

    invalid_status, _ = _transition(
        base_url,
        token,
        ticket_id,
        "CLOSED",
        1,
        f"gate0-invalid-{run_id}",
        timeout=timeout,
    )
    _expect(invalid_status, {400, 409}, "NEW to CLOSED denial")

    first_key = f"gate0-triage-{run_id}"
    status, ticket = _transition(
        base_url,
        token,
        ticket_id,
        "TRIAGE",
        1,
        first_key,
        timeout=timeout,
    )
    _expect(status, {200}, "NEW to TRIAGE")
    if ticket.get("governance_version") != 2:
        raise RuntimeError("NEW to TRIAGE did not advance governance_version to 2")
    replay_status, replay = _transition(
        base_url,
        token,
        ticket_id,
        "TRIAGE",
        1,
        first_key,
        timeout=timeout,
    )
    _expect(replay_status, {200}, "idempotent transition replay")
    if replay.get("governance_version") != 2:
        raise RuntimeError("idempotent replay changed governance_version")

    for target, version, suffix in (
        ("ASSIGNED", 2, "assign"),
        ("IN_PROGRESS", 3, "start"),
    ):
        status, ticket = _transition(
            base_url,
            token,
            ticket_id,
            target,
            version,
            f"gate0-{suffix}-{run_id}",
            timeout=timeout,
        )
        _expect(status, {200}, f"transition to {target}")

    race_targets = ("RESOLVED", "WAITING_USER")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _transition,
                base_url,
                token,
                ticket_id,
                target,
                4,
                f"gate0-race-{target.lower()}-{run_id}",
                timeout=timeout,
            )
            for target in race_targets
        ]
        race_results = [future.result(timeout=timeout + 5.0) for future in futures]
    race_codes = sorted(status_code for status_code, _ in race_results)
    if race_codes != [200, 409]:
        raise RuntimeError(f"concurrent transition result was {race_codes}, expected [200, 409]")
    winning_payload = next(payload for status_code, payload in race_results if status_code == 200)
    winning_status = str(winning_payload.get("status") or "")
    if winning_status not in race_targets or winning_payload.get("governance_version") != 5:
        raise RuntimeError("winning concurrent transition returned an invalid state/version")

    status, history = _request(
        base_url,
        "GET",
        f"/api/v1/tickets/{ticket_id}/history",
        token=token,
        timeout=timeout,
    )
    _expect(status, {200}, "ticket history")
    if not isinstance(history, list):
        raise RuntimeError("ticket history response is not a list")
    race_history = [
        item
        for item in history
        if item.get("field_name") == "status"
        and item.get("old_value") == "IN_PROGRESS"
        and item.get("new_value") in race_targets
    ]
    if len(race_history) != 1 or race_history[0].get("new_value") != winning_status:
        raise RuntimeError("history does not contain exactly one winning concurrent transition")
    triage_history = [
        item
        for item in history
        if item.get("field_name") == "status"
        and item.get("old_value") == "NEW"
        and item.get("new_value") == "TRIAGE"
    ]
    if len(triage_history) != 1:
        raise RuntimeError("idempotent replay produced duplicate NEW to TRIAGE history")

    cleanup_path = (
        (("CLOSED", 5),)
        if winning_status == "RESOLVED"
        else (("IN_PROGRESS", 5), ("RESOLVED", 6), ("CLOSED", 7))
    )
    for index, (target, version) in enumerate(cleanup_path):
        status, ticket = _transition(
            base_url,
            token,
            ticket_id,
            target,
            version,
            f"gate0-cleanup-{index}-{run_id}",
            timeout=timeout,
        )
        _expect(status, {200}, f"cleanup transition to {target}")
    if ticket.get("status") != "CLOSED":
        raise RuntimeError("QA ticket was not left in CLOSED state")

    logout_status, _ = _request(
        base_url,
        "POST",
        "/api/v1/auth/logout",
        token=token,
        payload={},
        timeout=timeout,
    )
    _expect(logout_status, {200}, "logout")
    return {
        "status": "PASS",
        "executed_at": datetime.now(UTC).isoformat(),
        "ticket_id": ticket_id,
        "final_status": "CLOSED",
        "race": {
            "targets": list(race_targets),
            "http_codes": race_codes,
            "winner": winning_status,
            "history_effects": len(race_history),
        },
        "idempotent_replay_history_effects": len(triage_history),
        "anonymous_transition_http_code": anonymous_status,
        "invalid_transition_http_code": invalid_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--email", default=os.environ.get("SBS_GATE0_EMAIL", ""))
    parser.add_argument("--password-env", default="SBS_GATE0_PASSWORD")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    password = os.environ.get(args.password_env, "")
    if not args.email or not password:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error": (
                        "Provide --email/SBS_GATE0_EMAIL and the password through "
                        f"the {args.password_env} environment variable"
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 2
    try:
        result = run(args.base_url, args.email, password, args.timeout)
    except RuntimeError as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
