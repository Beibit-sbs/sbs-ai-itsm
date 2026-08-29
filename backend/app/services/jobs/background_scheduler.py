"""Background task scheduler for continuous policy metrics polling."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db.session import SessionLocal
from app.services.audit import log_audit
from app.services.jobs.metrics_polling import poll_active_rollouts

logger = logging.getLogger("app.background_scheduler")


# Global scheduler instance
_scheduler: BackgroundScheduler | None = None
_scheduler_state = {
    "running": False,
    "started_at": None,
    "poll_count": 0,
    "poll_errors": 0,
}


def _metrics_polling_job() -> None:
    """Background job: Poll active rollout metrics and evaluate thresholds."""
    try:
        db = SessionLocal()
        try:
            stats = poll_active_rollouts(db)
            _scheduler_state["poll_count"] += 1

            if stats["errors"]:
                _scheduler_state["poll_errors"] += len(stats["errors"])
                logger.warning(
                    f"Polling completed with {len(stats['errors'])} errors: {stats['errors']}"
                )

            # Log polling event to audit trail
            log_audit(
                db,
                entity_type="policy_canary_rollout",
                entity_id="*",  # All rollouts
                action="policy.canary.polling_cycle",
                details={
                    "polled_count": stats["polled_count"],
                    "auto_rollback_count": stats["auto_rollback_count"],
                    "errors": stats["errors"],
                },
                user_id="system",
                change_reason="Scheduled polling cycle",
            )

            logger.info(
                f"Polling cycle completed: polled {stats['polled_count']}, "
                f"auto-rollbacks {stats['auto_rollback_count']}"
            )
        finally:
            db.close()
    except Exception as e:
        _scheduler_state["poll_errors"] += 1
        logger.error(f"Error in metrics polling job: {e}", exc_info=True)


def start_scheduler(
    poll_interval_seconds: int = 30,
) -> dict[str, Any]:
    """Start background scheduler with metrics polling job.

    Args:
        poll_interval_seconds: Polling interval in seconds (default: 30)

    Returns:
        Status dict with started_at, interval, and job_id
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        return {
            "status": "already_running",
            "started_at": _scheduler_state["started_at"],
            "poll_interval_seconds": poll_interval_seconds,
            "poll_count": _scheduler_state["poll_count"],
        }

    # Create scheduler
    _scheduler = BackgroundScheduler()

    # Add metrics polling job
    job = _scheduler.add_job(
        _metrics_polling_job,
        trigger=IntervalTrigger(seconds=poll_interval_seconds),
        id="metrics-polling-job",
        name="Metrics Polling",
        replace_existing=True,
    )

    # Start scheduler
    _scheduler.start()

    _scheduler_state["running"] = True
    _scheduler_state["started_at"] = datetime.now(UTC)
    _scheduler_state["poll_count"] = 0
    _scheduler_state["poll_errors"] = 0

    logger.info(
        f"Background scheduler started with metrics polling every {poll_interval_seconds}s"
    )

    return {
        "status": "started",
        "started_at": _scheduler_state["started_at"],
        "poll_interval_seconds": poll_interval_seconds,
        "job_id": job.id,
    }


def stop_scheduler() -> dict[str, Any]:
    """Stop background scheduler.

    Returns:
        Status dict with stopped_at, uptime, and final statistics
    """
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        return {"status": "not_running", "stopped_at": datetime.now(UTC)}

    started = _scheduler_state["started_at"]
    uptime = datetime.now(UTC) - started if started else None

    _scheduler.shutdown(wait=True)

    _scheduler_state["running"] = False

    logger.info("Background scheduler stopped")

    return {
        "status": "stopped",
        "stopped_at": datetime.now(UTC),
        "uptime_seconds": int(uptime.total_seconds()) if uptime is not None else None,
        "total_polls": _scheduler_state["poll_count"],
        "total_errors": _scheduler_state["poll_errors"],
    }


def get_scheduler_status() -> dict[str, Any]:
    """Get current scheduler status and statistics.

    Returns:
        Status dict with running state, uptime, and polling statistics
    """
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        return {
            "running": False,
            "started_at": None,
            "uptime_seconds": None,
            "poll_count": 0,
            "poll_errors": 0,
            "active_jobs": 0,
        }

    started = _scheduler_state["started_at"]
    uptime = datetime.now(UTC) - started if started else None

    return {
        "running": True,
        "started_at": started,
        "uptime_seconds": int(uptime.total_seconds()) if uptime is not None else None,
        "poll_count": _scheduler_state["poll_count"],
        "poll_errors": _scheduler_state["poll_errors"],
        "active_jobs": len(_scheduler.get_jobs()),
        "next_poll_in_seconds": _estimate_next_job_time(),
    }


def _estimate_next_job_time() -> int | None:
    """Estimate seconds until next job execution."""
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        return None

    jobs = _scheduler.get_jobs()
    if not jobs:
        return None

    job = jobs[0]
    if job.next_run_time is None:
        return None

    delta = job.next_run_time - datetime.now(UTC)
    return max(0, int(delta.total_seconds()))


def restart_scheduler(poll_interval_seconds: int = 30) -> dict[str, Any]:
    """Restart scheduler with optional new interval.

    Args:
        poll_interval_seconds: New polling interval in seconds (default: 30)

    Returns:
        Status dict with restart confirmation
    """
    global _scheduler

    # Stop current scheduler
    stop_result = stop_scheduler()

    # Start new scheduler
    start_result = start_scheduler(poll_interval_seconds)

    return {
        "status": "restarted",
        "stop_result": stop_result,
        "start_result": start_result,
    }


def get_scheduler_metrics() -> dict[str, Any]:
    """Get detailed scheduler metrics for monitoring.

    Returns:
        Comprehensive metrics dict
    """
    status = get_scheduler_status()

    # Calculate error rate
    error_rate = 0.0
    if status["poll_count"] > 0:
        error_rate = (status["poll_errors"] / status["poll_count"]) * 100

    return {
        **status,
        "error_rate_percent": round(error_rate, 2),
        "average_errors_per_poll": (
            round(status["poll_errors"] / status["poll_count"], 2)
            if status["poll_count"] > 0
            else 0.0
        ),
        "last_poll_time": _scheduler_state.get("last_poll_at"),
    }
