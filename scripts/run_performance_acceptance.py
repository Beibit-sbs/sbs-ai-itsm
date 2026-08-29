from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
import uuid

import aiohttp


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "performance" / "workload-profile.json"
MAX_LATENCY_SAMPLES = 2_000_000


class Evidence:
    def __init__(self) -> None:
        self.latencies_ms: list[float] = []
        self.statuses: Counter[int] = Counter()
        self.operations: Counter[str] = Counter()
        self.operation_latencies_ms: dict[str, list[float]] = defaultdict(list)
        self.websocket_attempts = 0
        self.websocket_failures = 0
        self.exceptions: Counter[str] = Counter()
        self._lock = asyncio.Lock()

    async def record_http(
        self,
        *,
        operation: str,
        status: int,
        duration_ms: float,
    ) -> None:
        async with self._lock:
            if len(self.latencies_ms) >= MAX_LATENCY_SAMPLES:
                raise RuntimeError(
                    f"Latency sample cap {MAX_LATENCY_SAMPLES} exceeded"
                )
            self.latencies_ms.append(duration_ms)
            self.statuses[status] += 1
            self.operations[operation] += 1
            self.operation_latencies_ms[operation].append(duration_ms)

    async def record_exception(self, exc: Exception) -> None:
        async with self._lock:
            self.exceptions[exc.__class__.__name__] += 1


async def _json_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    token: str | None,
    correlation_id: str,
    host_header: str | None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], float]:
    headers = {"X-Request-ID": correlation_id}
    if host_header:
        headers["Host"] = host_header
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    async with session.request(
        method,
        url,
        headers=headers,
        json=payload,
    ) as response:
        raw = await response.read()
        duration_ms = (time.perf_counter() - started) * 1000
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        return response.status, parsed if isinstance(parsed, dict) else {}, duration_ms


def _weighted_read(read_mix: list[dict[str, Any]]) -> dict[str, Any]:
    return random.choices(
        read_mix,
        weights=[int(item["weight"]) for item in read_mix],
        k=1,
    )[0]


async def _read_worker(
    worker_id: int,
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    token: str,
    read_mix: list[dict[str, Any]],
    write_percent: int,
    write_enabled: bool,
    write_flow: dict[str, Any],
    think_time_seconds: float,
    deadline: float,
    evidence: Evidence,
    email: str,
    host_header: str | None,
) -> None:
    while time.monotonic() < deadline:
        try:
            if write_enabled and random.randrange(100) < write_percent:
                correlation_id = f"load-{worker_id}-{uuid.uuid4()}"
                status, payload, duration_ms = await _json_request(
                    session,
                    "POST",
                    urljoin(base_url, str(write_flow["create_path"])),
                    token=token,
                    correlation_id=correlation_id,
                    host_header=host_header,
                    payload={
                        "title": f"[LOAD] governed lifecycle {correlation_id}",
                        "description": "PRG-006 controlled performance transaction",
                        "requester_name": "SBS Performance Monitor",
                        "requester_email": email,
                        "department": "Platform Operations",
                        "location": "Performance",
                        "category": "SOFTWARE_INSTALL",
                        "priority": "LOW",
                    },
                )
                await evidence.record_http(
                    operation="ticket_create",
                    status=status,
                    duration_ms=duration_ms,
                )
                ticket_id = str(payload.get("id") or "")
                if status == 201 and ticket_id:
                    for transition in write_flow["transitions"]:
                        transition_path = str(
                            write_flow["transition_path_template"]
                        ).format(ticket_id=ticket_id)
                        status, _, duration_ms = await _json_request(
                            session,
                            "POST",
                            urljoin(base_url, transition_path),
                            token=token,
                            correlation_id=correlation_id,
                            host_header=host_header,
                            payload={
                                "status": transition,
                                "comment": (
                                    "Controlled performance lifecycle; "
                                    f"correlation {correlation_id}"
                                ),
                            },
                        )
                        await evidence.record_http(
                            operation=f"ticket_transition_{transition}",
                            status=status,
                            duration_ms=duration_ms,
                        )
                        if status != 200:
                            break
            else:
                operation = _weighted_read(read_mix)
                correlation_id = f"load-{worker_id}-{uuid.uuid4()}"
                status, _, duration_ms = await _json_request(
                    session,
                    "GET",
                    urljoin(base_url, str(operation["path"])),
                    token=token,
                    correlation_id=correlation_id,
                    host_header=host_header,
                )
                await evidence.record_http(
                    operation=str(operation["name"]),
                    status=status,
                    duration_ms=duration_ms,
                )
        except Exception as exc:
            await evidence.record_exception(exc)
        await asyncio.sleep(think_time_seconds)


def _websocket_url(base_url: str, connection_url: str) -> str:
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    root = urlunsplit((scheme, parsed.netloc, "/", "", ""))
    return urljoin(root, connection_url.lstrip("/"))


async def _websocket_worker(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    token: str,
    deadline: float,
    evidence: Evidence,
    host_header: str | None,
) -> None:
    evidence.websocket_attempts += 1
    try:
        status, payload, _ = await _json_request(
            session,
            "POST",
            urljoin(base_url, "jobs/dashboard/socket-token"),
            token=token,
            correlation_id=f"load-ws-{uuid.uuid4()}",
            host_header=host_header,
        )
        if status != 200 or not payload.get("connection_url"):
            evidence.websocket_failures += 1
            return
        url = _websocket_url(base_url, str(payload["connection_url"]))
        websocket_headers = {"Host": host_header} if host_header else None
        async with session.ws_connect(
            url,
            headers=websocket_headers,
            heartbeat=20,
            receive_timeout=30,
        ) as ws:
            await ws.send_json({"action": "subscribe", "streams": ["summary"]})
            while time.monotonic() < deadline:
                try:
                    await ws.receive(timeout=min(10, max(0.1, deadline - time.monotonic())))
                except TimeoutError:
                    await ws.ping()
    except Exception as exc:
        evidence.websocket_failures += 1
        await evidence.record_exception(exc)


def _percentile(samples: list[float], percentile: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    document = json.loads(args.profile_file.read_text(encoding="utf-8"))
    profile = document["profiles"][args.profile]
    duration = args.duration_seconds or int(profile["duration_seconds"])
    concurrency = args.concurrency or int(profile["concurrency"])
    websocket_connections = (
        args.websocket_connections
        if args.websocket_connections is not None
        else int(profile["websocket_connections"])
    )
    write_percent = int(profile["write_percent"])
    if write_percent and not args.confirm_write_load:
        write_percent = 0

    password = args.password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("Password file is empty")

    timeout = aiohttp.ClientTimeout(total=args.request_timeout_seconds)
    connector = aiohttp.TCPConnector(
        limit=max(100, concurrency + websocket_connections + 10),
        ttl_dns_cache=60,
    )
    evidence = Evidence()
    started_at = datetime.now(UTC)
    base_url = args.base_url.rstrip("/") + "/"
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        login_status, login_payload, _ = await _json_request(
            session,
            "POST",
            urljoin(base_url, "auth/login"),
            token=None,
            correlation_id=f"load-login-{uuid.uuid4()}",
            host_header=args.host_header,
            payload={"email": args.email, "password": password},
        )
        if login_status != 200 or not login_payload.get("access_token"):
            raise RuntimeError(f"Load identity login failed with HTTP {login_status}")
        token = str(login_payload["access_token"])
        deadline = time.monotonic() + duration
        tasks = [
            asyncio.create_task(
                _read_worker(
                    worker_id,
                    session=session,
                    base_url=base_url,
                    token=token,
                    read_mix=document["read_mix"],
                    write_percent=write_percent,
                    write_enabled=args.confirm_write_load,
                    write_flow=document["write_flow"],
                    think_time_seconds=int(profile["think_time_ms"]) / 1000,
                    deadline=deadline,
                    evidence=evidence,
                    email=args.email,
                    host_header=args.host_header,
                )
            )
            for worker_id in range(concurrency)
        ]
        tasks.extend(
            asyncio.create_task(
                _websocket_worker(
                    session=session,
                    base_url=base_url,
                    token=token,
                    deadline=deadline,
                    evidence=evidence,
                    host_header=args.host_header,
                )
            )
            for _ in range(websocket_connections)
        )
        await asyncio.gather(*tasks)

    total = sum(evidence.statuses.values()) + sum(evidence.exceptions.values())
    failures = (
        sum(count for status, count in evidence.statuses.items() if status >= 400)
        + sum(evidence.exceptions.values())
    )
    websocket_failure_percent = (
        evidence.websocket_failures / evidence.websocket_attempts * 100
        if evidence.websocket_attempts
        else 0.0
    )
    summary = {
        "requests": total,
        "successful_http": sum(
            count for status, count in evidence.statuses.items() if status < 400
        ),
        "failed": failures,
        "http_error_percent": round(failures / max(total, 1) * 100, 4),
        "http_mean_ms": (
            round(statistics.fmean(evidence.latencies_ms), 3)
            if evidence.latencies_ms
            else 0.0
        ),
        "http_p50_ms": _percentile(evidence.latencies_ms, 0.50),
        "http_p95_ms": _percentile(evidence.latencies_ms, 0.95),
        "http_p99_ms": _percentile(evidence.latencies_ms, 0.99),
        "http_max_ms": (
            round(max(evidence.latencies_ms), 3) if evidence.latencies_ms else 0.0
        ),
        "websocket_attempts": evidence.websocket_attempts,
        "websocket_failures": evidence.websocket_failures,
        "websocket_failure_percent": round(websocket_failure_percent, 4),
        "statuses": dict(sorted(evidence.statuses.items())),
        "operations": dict(sorted(evidence.operations.items())),
        "exceptions": dict(sorted(evidence.exceptions.items())),
        "operation_latency_ms": {
            operation: {
                "count": len(samples),
                "mean": round(statistics.fmean(samples), 3),
                "p95": _percentile(samples, 0.95),
                "p99": _percentile(samples, 0.99),
                "max": round(max(samples), 3),
            }
            for operation, samples in sorted(
                evidence.operation_latencies_ms.items()
            )
            if samples
        },
    }
    thresholds = profile["thresholds"]
    checks = {
        "http_error_percent": (
            summary["http_error_percent"] <= thresholds["http_error_percent_max"]
        ),
        "http_p95_ms": summary["http_p95_ms"] <= thresholds["http_p95_ms_max"],
        "http_p99_ms": summary["http_p99_ms"] <= thresholds["http_p99_ms_max"],
        "websocket_failure_percent": (
            summary["websocket_failure_percent"]
            <= thresholds["websocket_failure_percent_max"]
        ),
    }
    result = {
        "schema_version": document["schema_version"],
        "status": "PASS" if all(checks.values()) and total > 0 else "FAIL",
        "profile": args.profile,
        "target": base_url,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "effective_load": {
            "duration_seconds": duration,
            "concurrency": concurrency,
            "websocket_connections": websocket_connections,
            "write_percent": write_percent,
            "write_enabled": args.confirm_write_load,
        },
        "thresholds": thresholds,
        "checks": checks,
        "summary": summary,
    }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded SBS API/WebSocket performance acceptance."
    )
    parser.add_argument("--profile-file", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--profile",
        choices=("baseline", "peak", "soak"),
        default="baseline",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--host-header")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int)
    parser.add_argument("--concurrency", type=int)
    parser.add_argument("--websocket-connections", type=int)
    parser.add_argument("--request-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--confirm-write-load",
        action="store_true",
        help="Required before the harness creates and closes load-test tickets.",
    )
    args = parser.parse_args()
    for field in ("duration_seconds", "concurrency", "websocket_connections"):
        value = getattr(args, field)
        if value is not None and value < 0:
            raise ValueError(f"{field} must not be negative")
    result = asyncio.run(_run(args))
    if args.output:
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
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
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
