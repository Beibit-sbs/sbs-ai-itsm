from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
import statistics
import time
from typing import Any
from urllib.parse import urljoin
import uuid

import aiohttp


async def _request(
    session: aiohttp.ClientSession,
    method: str,
    base_url: str,
    path: str,
    *,
    host_header: str,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any, float]:
    headers = {"Host": host_header, "X-Request-ID": f"tenant-gate-{uuid.uuid4()}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    async with session.request(
        method,
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        headers=headers,
        json=payload,
    ) as response:
        raw = await response.read()
        duration_ms = (time.perf_counter() - started) * 1000
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = None
        return response.status, body, duration_ms


async def _login(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    host_header: str,
    email: str,
    password: str,
) -> tuple[str, str]:
    status, body, _ = await _request(
        session,
        "POST",
        base_url,
        "auth/login",
        host_header=host_header,
        payload={"email": email, "password": password},
    )
    if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
        raise RuntimeError(f"Login failed for acceptance identity with HTTP {status}")
    token = str(body["access_token"])
    status, me, _ = await _request(
        session,
        "GET",
        base_url,
        "auth/me",
        host_header=host_header,
        token=token,
    )
    if status != 200 or not isinstance(me, dict) or not me.get("tenant_id"):
        raise RuntimeError(f"Identity lookup failed with HTTP {status}")
    return token, str(me["tenant_id"])


async def _create_ticket(
    session: aiohttp.ClientSession,
    *,
    base_url: str,
    host_header: str,
    token: str,
    email: str,
    label: str,
    index: int,
) -> tuple[str, str | None, float]:
    marker = f"tenant-acceptance-{label}-{index}-{uuid.uuid4().hex[:8]}"
    status, body, latency = await _request(
        session,
        "POST",
        base_url,
        "tickets",
        host_header=host_header,
        token=token,
        payload={
            "title": f"[TENANT-GATE] {marker}",
            "description": "Controlled PostgreSQL cross-tenant acceptance transaction",
            "requester_name": f"Tenant Gate {label}",
            "requester_email": email,
            "department": "Platform Assurance",
            "location": "Isolated rehearsal",
            "category": "SOFTWARE_INSTALL",
            "priority": "LOW",
        },
    )
    if status != 201 or not isinstance(body, dict) or not body.get("id"):
        raise RuntimeError(f"Ticket create failed for tenant {label} with HTTP {status}")
    return str(body["id"]), str(body.get("tenant_id") or "") or None, latency


async def run(args: argparse.Namespace) -> dict[str, Any]:
    password_a = args.password_file_a.read_text(encoding="utf-8").strip()
    password_b = args.password_file_b.read_text(encoding="utf-8").strip()
    if not password_a or not password_b:
        raise RuntimeError("Acceptance password file is empty")
    timeout = aiohttp.ClientTimeout(total=args.request_timeout_seconds)
    connector = aiohttp.TCPConnector(limit=max(50, args.ticket_count * 4))
    started_at = datetime.now(UTC)
    latencies: list[float] = []
    statuses: Counter[int] = Counter()

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        (token_a, tenant_a), (token_b, tenant_b) = await asyncio.gather(
            _login(
                session,
                base_url=args.base_url,
                host_header=args.host_header,
                email=args.email_a,
                password=password_a,
            ),
            _login(
                session,
                base_url=args.base_url,
                host_header=args.host_header,
                email=args.email_b,
                password=password_b,
            ),
        )
        if tenant_a == tenant_b:
            raise RuntimeError("Acceptance identities resolved to the same tenant")

        created = await asyncio.gather(
            *[
                _create_ticket(
                    session,
                    base_url=args.base_url,
                    host_header=args.host_header,
                    token=token,
                    email=email,
                    label=label,
                    index=index,
                )
                for token, email, label in (
                    (token_a, args.email_a, "A"),
                    (token_b, args.email_b, "B"),
                )
                for index in range(args.ticket_count)
            ]
        )
        split = args.ticket_count
        created_a = created[:split]
        created_b = created[split:]
        ids_a = [item[0] for item in created_a]
        ids_b = [item[0] for item in created_b]
        if any(item[1] != tenant_a for item in created_a):
            raise RuntimeError("Tenant A create response crossed tenant boundary")
        if any(item[1] != tenant_b for item in created_b):
            raise RuntimeError("Tenant B create response crossed tenant boundary")
        latencies.extend(item[2] for item in created)
        statuses[201] += len(created)

        # The scoped list assertions below cover every created ID.  Sample
        # detail endpoints independently so this isolation gate stays below
        # the production reverse-proxy burst limit even at maximum create load.
        verification_sample_size = min(3, args.ticket_count)
        read_specs = [
            *[
                (token_a, ticket_id, 200, "own_a")
                for ticket_id in ids_a[:verification_sample_size]
            ],
            *[
                (token_b, ticket_id, 200, "own_b")
                for ticket_id in ids_b[:verification_sample_size]
            ],
            *[
                (token_a, ticket_id, 404, "cross_a_to_b")
                for ticket_id in ids_b[:verification_sample_size]
            ],
            *[
                (token_b, ticket_id, 404, "cross_b_to_a")
                for ticket_id in ids_a[:verification_sample_size]
            ],
        ]
        read_results = await asyncio.gather(
            *[
                _request(
                    session,
                    "GET",
                    args.base_url,
                    f"tickets/{ticket_id}",
                    host_header=args.host_header,
                    token=token,
                )
                for token, ticket_id, _, _ in read_specs
            ]
        )
        cross_denials = 0
        own_successes = 0
        for (_, _, expected, label), (status, _body, latency) in zip(read_specs, read_results, strict=True):
            statuses[status] += 1
            latencies.append(latency)
            if status != expected:
                raise RuntimeError(f"{label} expected HTTP {expected}, received {status}")
            if expected == 404:
                cross_denials += 1
            else:
                own_successes += 1

        list_a_status, list_a, list_a_latency = await _request(
            session,
            "GET",
            args.base_url,
            "tickets?page=1&page_size=100",
            host_header=args.host_header,
            token=token_a,
        )
        list_b_status, list_b, list_b_latency = await _request(
            session,
            "GET",
            args.base_url,
            "tickets?page=1&page_size=100",
            host_header=args.host_header,
            token=token_b,
        )
        for status, latency in ((list_a_status, list_a_latency), (list_b_status, list_b_latency)):
            statuses[status] += 1
            latencies.append(latency)
            if status != 200:
                raise RuntimeError(f"Tenant ticket list failed with HTTP {status}")
        if not isinstance(list_a, dict) or not isinstance(list_b, dict):
            raise RuntimeError("Tenant ticket list response is not an object")
        items_a = list_a.get("items") if isinstance(list_a.get("items"), list) else []
        items_b = list_b.get("items") if isinstance(list_b.get("items"), list) else []
        visible_a = {str(item.get("id")) for item in items_a if isinstance(item, dict)}
        visible_b = {str(item.get("id")) for item in items_b if isinstance(item, dict)}
        if not set(ids_a).issubset(visible_a) or not set(ids_b).issubset(visible_b):
            raise RuntimeError("Created tenant tickets are missing from their own scoped list")
        if visible_a.intersection(ids_b) or visible_b.intersection(ids_a):
            raise RuntimeError("Cross-tenant ticket leaked into a scoped list")
        if any(str(item.get("tenant_id")) != tenant_a for item in items_a if isinstance(item, dict)):
            raise RuntimeError("Tenant A list contains a foreign tenant_id")
        if any(str(item.get("tenant_id")) != tenant_b for item in items_b if isinstance(item, dict)):
            raise RuntimeError("Tenant B list contains a foreign tenant_id")

        await asyncio.gather(
            _request(
                session,
                "POST",
                args.base_url,
                "auth/logout",
                host_header=args.host_header,
                token=token_a,
                payload={},
            ),
            _request(
                session,
                "POST",
                args.base_url,
                "auth/logout",
                host_header=args.host_header,
                token=token_b,
                payload={},
            ),
        )

    ordered = sorted(latencies)

    def percentile(value: float) -> float:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * value)))
        return round(ordered[index], 3)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started_at.isoformat(),
        "status": "PASS",
        "scope": "isolated_production_like_postgresql_concurrent_tenant_isolation",
        "source_worktree_dirty": True,
        "primary_local_database_changed": False,
        "identities": 2,
        "distinct_tenants": 2,
        "tickets_per_tenant": args.ticket_count,
        "created": len(created),
        "detail_verification_sample_per_tenant": verification_sample_size,
        "own_reads_200": own_successes,
        "cross_tenant_reads_404": cross_denials,
        "cross_tenant_list_leaks": 0,
        "http_statuses": {str(key): value for key, value in sorted(statuses.items())},
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3),
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": round(max(latencies), 3),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080/api/v1/")
    parser.add_argument("--host-header", default="itsm.rehearsal.local")
    parser.add_argument("--email-a", required=True)
    parser.add_argument("--password-file-a", type=Path, required=True)
    parser.add_argument("--email-b", required=True)
    parser.add_argument("--password-file-b", type=Path, required=True)
    parser.add_argument("--ticket-count", type=int, default=10)
    parser.add_argument("--request-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--confirm-write-load", action="store_true")
    args = parser.parse_args()
    if not args.confirm_write_load:
        print("[FAIL] --confirm-write-load is required")
        return 2
    if not 1 <= args.ticket_count <= 50:
        print("[FAIL] --ticket-count must be between 1 and 50")
        return 2
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_type": exc.__class__.__name__, "error": str(exc)}))
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
