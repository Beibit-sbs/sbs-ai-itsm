from __future__ import annotations

import asyncio
import logging

from redis import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.jobs import execute_job, get_job
from app.services.jobs import tasks as _job_tasks  # noqa: F401 - registers built-in tasks

logger = logging.getLogger("app.jobs.worker")


def _requeue_missing_job(redis_client: Redis, queue_name: str, job_id: str) -> None:
    attempts_key = f"jobs:missing-retry:{job_id}"
    attempts = int(redis_client.incr(attempts_key))
    redis_client.expire(attempts_key, 60)
    if attempts <= 5:
        redis_client.rpush(queue_name, job_id)
        logger.warning("job_not_found_requeued", extra={"job_id": job_id, "attempt": attempts})
        return
    logger.error("job_not_found_dropped", extra={"job_id": job_id, "attempt": attempts})


def _run_single_job(job_id: str, *, redis_client: Redis, queue_name: str) -> None:
    db = SessionLocal()
    try:
        job = get_job(db, job_id)
        if job is None:
            _requeue_missing_job(redis_client, queue_name, job_id)
            return
        if job.status != "queued":
            logger.info("job_skip_non_queued", extra={"job_id": job_id, "status": job.status})
            return
        asyncio.run(execute_job(db, job))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("job_worker_processing_failed", extra={"job_id": job_id})
    finally:
        db.close()


def run_worker_forever() -> None:
    settings = get_settings()
    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=30,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    logger.info(
        "jobs_worker_started",
        extra={"queue": settings.jobs_queue_name, "redis_url": settings.redis_url, "executor": settings.jobs_executor_mode},
    )
    try:
        while True:
            try:
                item = redis_client.brpop(settings.jobs_queue_name, timeout=5)
            except RedisTimeoutError:
                # BRPOP can exceed socket read timeout in some environments;
                # keep the worker alive and continue polling.
                continue
            if item is None:
                continue
            _, job_id = item
            _run_single_job(str(job_id), redis_client=redis_client, queue_name=settings.jobs_queue_name)
    except KeyboardInterrupt:
        logger.info("jobs_worker_stopped")
    finally:
        redis_client.close()


if __name__ == "__main__":
    run_worker_forever()
