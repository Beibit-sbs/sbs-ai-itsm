"""Built-in tasks registered on module import.

Additional tasks are registered from their respective modules; this file only
defines observability-safe, side-effect-free primitives used by tests and
system smoke checks.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.services.jobs import register_task


async def echo_task(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Return payload with metadata; used for readiness smoke and tests."""

    return {
        "echoed": payload,
        "task_name": ctx.get("task_name"),
        "attempt": ctx.get("attempt"),
    }


async def sleep_task(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Sleep for a short duration; caps at 1s so it can never wedge tests."""

    seconds = float(payload.get("seconds") or 0)
    seconds = max(0.0, min(1.0, seconds))
    await asyncio.sleep(seconds)
    return {"slept_seconds": seconds}


async def fail_task(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Deliberately raise; used for failure path tests."""

    reason = str(payload.get("reason") or "intentional failure")
    raise RuntimeError(reason)


register_task("system.echo", echo_task)
register_task("system.sleep", sleep_task)
register_task("system.fail", fail_task)


__all__ = ["echo_task", "sleep_task", "fail_task"]
